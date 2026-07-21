//! Owned intermediate representation for the Aether compiler.
//!
//! This crate contains the data model and schema boundary shared by later
//! compiler phases. It intentionally performs no semantic verification,
//! parsing, optimization, or compiler integration.

mod block;
mod constant;
mod function;
mod importer;
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
pub use importer::{
    IRImportError, import_constant, import_enum_constant, import_instruction,
    import_optional_source_location, import_parameter, import_source_location, import_storage,
    import_type, import_value,
};
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
