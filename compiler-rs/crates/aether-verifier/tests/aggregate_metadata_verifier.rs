//! Focused aggregate shape, dimension, and cardinality verifier coverage.

use std::error::Error as _;

use aether_ir::{
    BoolType, IRBasicBlock, IRFunction, IRInstruction, IRModule, IRType, IRValue, IntType,
    MatrixType, VectorType, VoidType,
};
use aether_verifier::{
    BlockTypeVerificationError, FunctionTypeVerificationError, InstructionKind,
    InstructionTypeVerificationError, ModuleTypeVerificationError, TypeRuleError,
    verify_module_types,
};

fn value(name: &str, type_: IRType) -> IRValue {
    IRValue::new(name, type_)
}

fn vector(orientation: &str) -> IRType {
    VectorType {
        element: Box::new(IntType.into()),
        orientation: Some(orientation.to_owned()),
    }
    .into()
}

fn matrix() -> IRType {
    MatrixType {
        element: Box::new(IntType.into()),
    }
    .into()
}

fn module_with_instruction(instruction: IRInstruction) -> IRModule {
    let mut block = IRBasicBlock::new("entry");
    block.instructions.push(instruction);
    let mut function = IRFunction::new("main", Vec::new(), VoidType.into());
    function.blocks.push(block);
    IRModule {
        functions: vec![function],
        structs: Vec::new(),
    }
}

fn failure(instruction: IRInstruction) -> (InstructionKind, TypeRuleError) {
    let error = verify_module_types(&module_with_instruction(instruction)).unwrap_err();
    let ModuleTypeVerificationError::Function { source, .. } = error else {
        panic!("expected function error")
    };
    let FunctionTypeVerificationError::Block { source, .. } = source else {
        panic!("expected block error")
    };
    (source.instruction_kind, source.source.source)
}

fn compare(type_: IRType, aggregate_shape: Option<Vec<i64>>) -> IRInstruction {
    IRInstruction::IRCompareOp {
        result: value("result", BoolType.into()),
        operator: "eq".to_owned(),
        left: value("left", type_.clone()),
        right: value("right", type_),
        aggregate_shape,
    }
}

fn print(type_: IRType, aggregate_shape: Option<Vec<i64>>) -> IRInstruction {
    IRInstruction::IRPrint {
        value: value("printed", type_),
        newline: true,
        aggregate_shape,
    }
}

#[test]
fn compare_enforces_scalar_vector_and_matrix_shape_contracts() {
    assert_eq!(
        verify_module_types(&module_with_instruction(compare(IntType.into(), None))),
        Ok(())
    );
    assert_eq!(
        verify_module_types(&module_with_instruction(compare(
            vector("row"),
            Some(vec![1])
        ))),
        Ok(())
    );
    for shape in [vec![1, 1], vec![1, 4], vec![4, 1]] {
        assert_eq!(
            verify_module_types(&module_with_instruction(compare(matrix(), Some(shape)))),
            Ok(())
        );
    }

    for (type_, shape, expected_rank, actual) in [
        (IntType.into(), Some(Vec::new()), 0, Some(Vec::new())),
        (vector("row"), None, 1, None),
        (vector("row"), Some(vec![1, 1]), 1, Some(vec![1, 1])),
        (vector("row"), Some(vec![0]), 1, Some(vec![0])),
        (vector("row"), Some(vec![-1]), 1, Some(vec![-1])),
        (matrix(), Some(vec![1]), 2, Some(vec![1])),
        (matrix(), Some(vec![1, 0]), 2, Some(vec![1, 0])),
        (matrix(), Some(vec![-1, 1]), 2, Some(vec![-1, 1])),
    ] {
        let (kind, rule) = failure(compare(type_, shape));
        assert_eq!(kind, InstructionKind::IRCompareOp);
        assert_eq!(
            rule,
            TypeRuleError::InvalidAggregateShape {
                field: "aggregate_shape".to_owned(),
                expected_rank,
                requires_positive_dimensions: expected_rank != 0,
                actual,
            }
        );
    }
}

#[test]
fn print_enforces_shape_presence_and_rank_without_dimension_positivity() {
    assert_eq!(
        verify_module_types(&module_with_instruction(print(IntType.into(), None))),
        Ok(())
    );
    for shape in [vec![1], vec![0], vec![-1]] {
        assert_eq!(
            verify_module_types(&module_with_instruction(print(
                vector("column"),
                Some(shape)
            ))),
            Ok(())
        );
    }
    for shape in [vec![1, 1], vec![0, 3], vec![-1, 2]] {
        assert_eq!(
            verify_module_types(&module_with_instruction(print(matrix(), Some(shape)))),
            Ok(())
        );
    }

    for (type_, shape, expected_rank, actual) in [
        (IntType.into(), Some(vec![1]), 0, Some(vec![1])),
        (vector("row"), None, 1, None),
        (vector("row"), Some(vec![1, 1]), 1, Some(vec![1, 1])),
        (matrix(), None, 2, None),
        (matrix(), Some(vec![1]), 2, Some(vec![1])),
    ] {
        let (kind, rule) = failure(print(type_, shape));
        assert_eq!(kind, InstructionKind::IRPrint);
        assert_eq!(
            rule,
            TypeRuleError::InvalidAggregateShape {
                field: "aggregate_shape".to_owned(),
                expected_rank,
                requires_positive_dimensions: false,
                actual,
            }
        );
    }
}

#[test]
fn vector_literal_cardinality_matches_python_empty_literal_policy() {
    for element_count in [0, 1, 4] {
        let instruction = IRInstruction::IRVectorNew {
            result: value("result", vector("row")),
            elements: (0..element_count)
                .map(|index| value(&format!("element{index}"), IntType.into()))
                .collect(),
            orientation: Some("row".to_owned()),
        };
        assert_eq!(
            verify_module_types(&module_with_instruction(instruction)),
            Ok(())
        );
    }
}

fn vector_dimension_instructions(length: i64) -> Vec<IRInstruction> {
    let row = vector("row");
    let column = vector("column");
    vec![
        IRInstruction::IRVectorAdd {
            result: value("result", row.clone()),
            left: value("left", row.clone()),
            right: value("right", row.clone()),
            length,
            orientation: Some("row".to_owned()),
        },
        IRInstruction::IRVectorSub {
            result: value("result", row.clone()),
            left: value("left", row.clone()),
            right: value("right", row.clone()),
            length,
            orientation: Some("row".to_owned()),
        },
        IRInstruction::IRVectorScale {
            result: value("result", row.clone()),
            vector: value("vector", row.clone()),
            scalar: value("scalar", IntType.into()),
            length,
            orientation: Some("row".to_owned()),
        },
        IRInstruction::IRVectorDot {
            result: value("result", IntType.into()),
            left: value("left", row),
            right: value("right", column),
            length,
        },
    ]
}

#[test]
fn every_retained_vector_length_must_be_positive() {
    for instruction in vector_dimension_instructions(1) {
        assert_eq!(
            verify_module_types(&module_with_instruction(instruction)),
            Ok(())
        );
    }
    for length in [0, -1] {
        for instruction in vector_dimension_instructions(length) {
            let (_, rule) = failure(instruction);
            assert_eq!(
                rule,
                TypeRuleError::InvalidVectorLength {
                    field: "length".to_owned(),
                    actual: length,
                }
            );
        }
    }
}

fn matrix_dimension_instructions(dimension: i64) -> Vec<IRInstruction> {
    let matrix_type = matrix();
    let row = vector("row");
    let column = vector("column");
    let int: IRType = IntType.into();
    vec![
        IRInstruction::IROuterProduct {
            result: value("result", matrix_type.clone()),
            column: value("column", column.clone()),
            row: value("row", row.clone()),
            rows: dimension,
            cols: 1,
        },
        IRInstruction::IRMatrixAdd {
            result: value("result", matrix_type.clone()),
            left: value("left", matrix_type.clone()),
            right: value("right", matrix_type.clone()),
            rows: 1,
            cols: dimension,
        },
        IRInstruction::IRMatrixSub {
            result: value("result", matrix_type.clone()),
            left: value("left", matrix_type.clone()),
            right: value("right", matrix_type.clone()),
            rows: dimension,
            cols: 1,
        },
        IRInstruction::IRMatrixScale {
            result: value("result", matrix_type.clone()),
            matrix: value("matrix", matrix_type.clone()),
            scalar: value("scalar", int.clone()),
            rows: 1,
            cols: dimension,
        },
        IRInstruction::IRMatrixMatMul {
            result: value("result", matrix_type.clone()),
            left: value("left", matrix_type.clone()),
            right: value("right", matrix_type.clone()),
            rows: 1,
            inner: dimension,
            cols: 1,
        },
        IRInstruction::IRMatrixVectorMul {
            result: value("result", column.clone()),
            matrix: value("matrix", matrix_type.clone()),
            vector: value("vector", column.clone()),
            rows: dimension,
            inner: 1,
        },
        IRInstruction::IRVectorMatrixMul {
            result: value("result", row.clone()),
            vector: value("vector", row),
            matrix: value("matrix", matrix_type.clone()),
            rows: 1,
            cols: dimension,
        },
        IRInstruction::IRMatrixGet {
            result: value("result", int.clone()),
            matrix: value("matrix", matrix_type.clone()),
            row: value("row", int.clone()),
            column: value("column", int.clone()),
            cols: dimension,
        },
        IRInstruction::IRMatrixSet {
            matrix: value("matrix", matrix_type.clone()),
            row: value("row", int.clone()),
            column: value("column", int.clone()),
            value: value("value", int.clone()),
            cols: dimension,
        },
        IRInstruction::IRMatrixRows {
            result: value("result", int.clone()),
            matrix: value("matrix", matrix_type.clone()),
            rows: dimension,
        },
        IRInstruction::IRMatrixColumns {
            result: value("result", int),
            matrix: value("matrix", matrix_type),
            columns: dimension,
        },
    ]
}

#[test]
fn every_retained_matrix_dimension_must_be_positive() {
    for instruction in matrix_dimension_instructions(1) {
        assert_eq!(
            verify_module_types(&module_with_instruction(instruction)),
            Ok(())
        );
    }
    for dimension in [0, -1] {
        for instruction in matrix_dimension_instructions(dimension) {
            let (_, rule) = failure(instruction);
            assert!(matches!(
                rule,
                TypeRuleError::InvalidMatrixDimensions { actual, .. }
                    if actual.contains(&dimension)
            ));
        }
    }
}

fn matrix_new(rows: i64, columns: i64, element_count: usize) -> IRInstruction {
    IRInstruction::IRMatrixNew {
        result: value("result", matrix()),
        elements: (0..element_count)
            .map(|index| value(&format!("element{index}"), IntType.into()))
            .collect(),
        rows,
        cols: columns,
    }
}

#[test]
fn matrix_literals_require_positive_dimensions_and_exact_cardinality() {
    for (rows, columns, count) in [(1, 1, 1), (1, 4, 4), (4, 1, 4), (2, 3, 6)] {
        assert_eq!(
            verify_module_types(&module_with_instruction(matrix_new(rows, columns, count))),
            Ok(())
        );
    }

    for (rows, columns) in [(0, 1), (1, 0), (-1, 1), (1, -1)] {
        let (kind, rule) = failure(matrix_new(rows, columns, 0));
        assert_eq!(kind, InstructionKind::IRMatrixNew);
        assert!(matches!(
            rule,
            TypeRuleError::InvalidMatrixDimensions {
                fields,
                actual,
            } if fields == ["rows", "cols"] && actual == [rows, columns]
        ));
    }

    for actual in [5, 7] {
        let (kind, rule) = failure(matrix_new(2, 3, actual));
        assert_eq!(kind, InstructionKind::IRMatrixNew);
        assert_eq!(
            rule,
            TypeRuleError::InvalidMatrixCardinality {
                rows: 2,
                columns: 3,
                expected: 6,
                actual,
            }
        );
    }
}

#[test]
fn aggregate_metadata_diagnostics_keep_the_complete_downcastable_source_chain() {
    let error = verify_module_types(&module_with_instruction(compare(
        vector("row"),
        Some(vec![0]),
    )))
    .unwrap_err();
    let function = error
        .source()
        .and_then(|source| source.downcast_ref::<FunctionTypeVerificationError>())
        .expect("module error must source the function error");
    let block = function
        .source()
        .and_then(|source| source.downcast_ref::<BlockTypeVerificationError>())
        .expect("function error must source the block error");
    let instruction = block
        .source()
        .and_then(|source| source.downcast_ref::<InstructionTypeVerificationError>())
        .expect("block error must source the instruction error");
    let rule = instruction
        .source()
        .and_then(|source| source.downcast_ref::<TypeRuleError>())
        .expect("instruction error must source the typed rule");

    assert_eq!(instruction.instruction_kind, InstructionKind::IRCompareOp);
    assert!(matches!(
        rule,
        TypeRuleError::InvalidAggregateShape {
            expected_rank: 1,
            actual: Some(actual),
            ..
        } if actual == &[0]
    ));
}
