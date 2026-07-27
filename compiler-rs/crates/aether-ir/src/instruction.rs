//! Instruction variants in the initial Aether IR.

use crate::{IRConstant, IRSourceLocation, IRStorage, IRValue, LifecycleSource};

/// An instruction in the initial, pre-SSA Aether IR.
///
/// Variant names and payload fields mirror the Python instruction dataclasses.
/// Signed metadata fields intentionally permit malformed shapes and indices;
/// validation belongs to the separate verifier crate.
#[derive(Clone, Debug, PartialEq)]
#[allow(missing_docs, clippy::enum_variant_names, clippy::large_enum_variant)]
pub enum IRInstruction {
    /// Defines a constant value.
    IRConst { result: IRValue, value: IRConstant },
    /// Loads a value from a mutable slot.
    IRLoad { result: IRValue, slot: IRValue },
    /// Stores a value into a mutable slot.
    IRStore { slot: IRValue, value: IRValue },
    /// Default-initializes owning storage.
    IRInitDefault {
        destination: IRStorage,
        source_location: Option<IRSourceLocation>,
    },
    /// Copy-initializes owning storage.
    IRCopyInit {
        destination: IRStorage,
        source: LifecycleSource,
        source_location: Option<IRSourceLocation>,
    },
    /// Move-initializes owning storage.
    IRMoveInit {
        destination: IRStorage,
        source: IRStorage,
        source_location: Option<IRSourceLocation>,
    },
    /// Assigns to live owning storage.
    IRAssign {
        destination: IRStorage,
        source: LifecycleSource,
        source_location: Option<IRSourceLocation>,
    },
    /// Destroys a live owning storage location.
    IRDestroy {
        value: IRStorage,
        source_location: Option<IRSourceLocation>,
    },
    /// Relocates a sequence of owning storage locations.
    IRRelocate {
        destination: IRStorage,
        source: IRStorage,
        count: i64,
        source_location: Option<IRSourceLocation>,
    },
    /// Applies a binary operator.
    IRBinaryOp {
        result: IRValue,
        operator: String,
        left: IRValue,
        right: IRValue,
        source_location: Option<IRSourceLocation>,
    },
    /// Applies a unary operator.
    IRUnaryOp {
        result: IRValue,
        operator: String,
        operand: IRValue,
    },
    /// Compares scalar or aggregate operands.
    IRCompareOp {
        result: IRValue,
        operator: String,
        left: IRValue,
        right: IRValue,
        aggregate_shape: Option<Vec<i64>>,
    },
    /// Casts a value to the result type.
    IRCast { result: IRValue, value: IRValue },
    /// Calls a directly named function or builtin.
    IRCall {
        function: String,
        arguments: Vec<IRValue>,
        result: Option<IRValue>,
        builtin: Option<String>,
        source_location: Option<IRSourceLocation>,
    },
    /// Creates a typed reference to a directly named function.
    IRFunctionRef { result: IRValue, function: String },
    /// Calls a function value indirectly.
    IRCallIndirect {
        callee: IRValue,
        arguments: Vec<IRValue>,
        result: Option<IRValue>,
    },
    /// Prints a scalar or aggregate value.
    IRPrint {
        value: IRValue,
        newline: bool,
        aggregate_shape: Option<Vec<i64>>,
    },
    /// Constructs a struct value.
    IRStructNew {
        result: IRValue,
        fields: Vec<IRValue>,
    },
    /// Allocates a payload-free nominal class object.
    IRClassNew { result: IRValue },
    /// Reads a named struct field.
    IRStructGet {
        result: IRValue,
        r#struct: IRValue,
        field_index: i64,
        field_name: String,
    },
    /// Produces a struct value with one field replaced.
    IRStructSet {
        result: IRValue,
        r#struct: IRValue,
        field_index: i64,
        field_name: String,
        value: IRValue,
    },
    /// Constructs the receiver/value pair returned by a method.
    IRMethodResultNew {
        result: IRValue,
        receiver: IRValue,
        value: Option<IRValue>,
    },
    /// Extracts the receiver from a method result.
    IRMethodResultReceiver {
        result: IRValue,
        method_result: IRValue,
    },
    /// Extracts the source-level value from a method result.
    IRMethodResultValue {
        result: IRValue,
        method_result: IRValue,
    },
    /// Allocates and initializes an array.
    IRArrayNew {
        result: IRValue,
        elements: Vec<IRValue>,
    },
    /// Allocates and initializes a list.
    IRListNew {
        result: IRValue,
        elements: Vec<IRValue>,
    },
    /// Copies an array.
    IRArrayCopy {
        result: IRValue,
        array: IRValue,
        source_location: Option<IRSourceLocation>,
    },
    /// Copies a list.
    IRListCopy {
        result: IRValue,
        list_value: IRValue,
        source_location: Option<IRSourceLocation>,
    },
    /// Tests whether a list contains a value.
    IRListContains {
        result: IRValue,
        list_value: IRValue,
        value: IRValue,
    },
    /// Finds the first index of a value in a list.
    IRListIndexOf {
        result: IRValue,
        list_value: IRValue,
        value: IRValue,
    },
    /// Removes every element from a list.
    IRListClear { list_value: IRValue },
    /// Appends a value to a list.
    IRListPush { list_value: IRValue, value: IRValue },
    /// Inserts a value into a list.
    IRListInsert {
        list_value: IRValue,
        index: IRValue,
        value: IRValue,
    },
    /// Removes and returns the list element at an index.
    IRListRemoveAt {
        result: IRValue,
        list_value: IRValue,
        index: IRValue,
    },
    /// Removes and returns the last list element.
    IRListPop {
        result: IRValue,
        list_value: IRValue,
    },
    /// Reverses a list in place.
    IRListReverse { list_value: IRValue },
    /// Sorts a supported sequence in place.
    IRSequenceSort { sequence: IRValue },
    /// Allocates and initializes a vector.
    IRVectorNew {
        result: IRValue,
        elements: Vec<IRValue>,
        orientation: Option<String>,
    },
    /// Allocates and initializes a matrix.
    IRMatrixNew {
        result: IRValue,
        elements: Vec<IRValue>,
        rows: i64,
        cols: i64,
    },
    /// Adds two vectors.
    IRVectorAdd {
        result: IRValue,
        left: IRValue,
        right: IRValue,
        length: i64,
        orientation: Option<String>,
    },
    /// Subtracts two vectors.
    IRVectorSub {
        result: IRValue,
        left: IRValue,
        right: IRValue,
        length: i64,
        orientation: Option<String>,
    },
    /// Multiplies a vector by a scalar.
    IRVectorScale {
        result: IRValue,
        vector: IRValue,
        scalar: IRValue,
        length: i64,
        orientation: Option<String>,
    },
    /// Computes `Vector<Row> * Vector<Column>`.
    IRVectorDot {
        result: IRValue,
        left: IRValue,
        right: IRValue,
        length: i64,
    },
    /// Computes `Vector<Column> * Vector<Row>`.
    IROuterProduct {
        result: IRValue,
        column: IRValue,
        row: IRValue,
        rows: i64,
        cols: i64,
    },
    /// Adds two matrices.
    IRMatrixAdd {
        result: IRValue,
        left: IRValue,
        right: IRValue,
        rows: i64,
        cols: i64,
    },
    /// Subtracts two matrices.
    IRMatrixSub {
        result: IRValue,
        left: IRValue,
        right: IRValue,
        rows: i64,
        cols: i64,
    },
    /// Multiplies a matrix by a scalar.
    IRMatrixScale {
        result: IRValue,
        matrix: IRValue,
        scalar: IRValue,
        rows: i64,
        cols: i64,
    },
    /// Multiplies two matrices.
    IRMatrixMatMul {
        result: IRValue,
        left: IRValue,
        right: IRValue,
        rows: i64,
        inner: i64,
        cols: i64,
    },
    /// Multiplies a matrix by a column vector.
    IRMatrixVectorMul {
        result: IRValue,
        matrix: IRValue,
        vector: IRValue,
        rows: i64,
        inner: i64,
    },
    /// Multiplies a row vector by a matrix.
    IRVectorMatrixMul {
        result: IRValue,
        vector: IRValue,
        matrix: IRValue,
        rows: i64,
        cols: i64,
    },
    /// Reads an array element.
    IRArrayGet {
        result: IRValue,
        array: IRValue,
        index: IRValue,
        borrowed: bool,
        borrow_scope: Option<String>,
        source_location: Option<IRSourceLocation>,
    },
    /// Copies a range of an array.
    IRArraySlice {
        result: IRValue,
        array: IRValue,
        start: IRValue,
        end: IRValue,
        source_location: Option<IRSourceLocation>,
    },
    /// Copies a range of a list.
    IRListSlice {
        result: IRValue,
        list_value: IRValue,
        start: IRValue,
        end: IRValue,
        source_location: Option<IRSourceLocation>,
    },
    /// Reads a list element.
    IRListGet {
        result: IRValue,
        list_value: IRValue,
        index: IRValue,
        borrowed: bool,
        borrow_scope: Option<String>,
        source_location: Option<IRSourceLocation>,
    },
    /// Reads a vector element.
    IRVectorGet {
        result: IRValue,
        vector: IRValue,
        index: IRValue,
    },
    /// Reads a matrix element.
    IRMatrixGet {
        result: IRValue,
        matrix: IRValue,
        row: IRValue,
        column: IRValue,
        cols: i64,
    },
    /// Reads a vector's dynamic length.
    IRVectorLength { result: IRValue, vector: IRValue },
    /// Materializes a matrix's retained row count.
    IRMatrixRows {
        result: IRValue,
        matrix: IRValue,
        rows: i64,
    },
    /// Materializes a matrix's retained column count.
    IRMatrixColumns {
        result: IRValue,
        matrix: IRValue,
        columns: i64,
    },
    /// Assigns an array element.
    IRArraySet {
        array: IRValue,
        index: IRValue,
        value: IRValue,
    },
    /// Assigns a list element.
    IRListSet {
        list_value: IRValue,
        index: IRValue,
        value: IRValue,
    },
    /// Assigns a vector element.
    IRVectorSet {
        vector: IRValue,
        index: IRValue,
        value: IRValue,
    },
    /// Assigns a matrix element.
    IRMatrixSet {
        matrix: IRValue,
        row: IRValue,
        column: IRValue,
        value: IRValue,
        cols: i64,
    },
    /// Reads an array's dynamic length.
    IRArrayLength { result: IRValue, array: IRValue },
    /// Reads a list's dynamic length.
    IRListLength {
        result: IRValue,
        list_value: IRValue,
    },
    /// Tests whether a list is empty.
    IRListIsEmpty {
        result: IRValue,
        list_value: IRValue,
    },
    /// Selects one of two successor blocks.
    IRBranch {
        condition: IRValue,
        true_target: String,
        false_target: String,
    },
    /// Transfers control to one successor block.
    IRJump { target: String },
    /// Returns from the current function.
    IRReturn {
        value: Option<LifecycleSource>,
        transferred_storage: Option<IRStorage>,
    },
}
