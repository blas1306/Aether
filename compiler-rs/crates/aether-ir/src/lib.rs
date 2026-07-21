//! Owned intermediate representation for the Aether compiler.
//!
//! This crate contains only the data model shared by later compiler phases. It
//! intentionally performs no verification, parsing, optimization, conversion,
//! or compiler integration.

mod block;
mod constant;
mod function;
mod instruction;
mod module;
mod source;
mod structure;
mod types;
mod value;
pub mod wire;

pub use block::IRBasicBlock;
pub use constant::{IRConstant, IREnumConstant};
pub use function::IRFunction;
pub use instruction::IRInstruction;
pub use module::IRModule;
pub use source::IRSourceLocation;
pub use structure::IRStructDefinition;
pub use types::{
    ArrayType, BoolType, ClassRefType, ComplexType, DoubleType, EnumType, FloatType, FunctionType,
    IRType, IntType, InterfaceType, ListType, MatrixType, MethodResultType, NullableType,
    StringType, StructType, VectorType, VoidType,
};
pub use value::{IRParameter, IRStorage, IRValue};
