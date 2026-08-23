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
mod json;
mod lifecycle;
mod lowering;
mod module;
mod source;
mod ssa;
mod structure;
mod types;
mod value;
pub mod wire;

pub use block::IRBasicBlock;
pub use constant::{IRConstant, IREnumConstant};
pub use function::IRFunction;
pub use importer::{
    IRImportError, import_basic_block, import_constant, import_enum_constant, import_function,
    import_instruction, import_module, import_optional_source_location, import_parameter,
    import_source_location, import_storage, import_struct_definition, import_type, import_value,
};
pub use instruction::{IRErasedBoxLayout, IRInstruction, IRWitnessMethodSlot, IRWitnessTable};
pub use json::{IRModuleJsonImportError, import_module_json, parse_strict_json_value};
pub use lifecycle::{
    LifecycleNormalizationError, lower_verified_ir_to_ssa_v1, normalize_lifecycle_v1,
};
pub use lowering::{
    SsaLoweringError, SsaLoweringPhaseTimings, characterize_lower_normalized_ir_to_ssa_v1,
    lower_normalized_ir_to_ssa_v1,
};
pub use module::IRModule;
pub use source::IRSourceLocation;
pub use ssa::{
    BlockId, FunctionId, OwnedSsaBlock, OwnedSsaCodecError, OwnedSsaFunction, OwnedSsaInstruction,
    OwnedSsaModule, PhiIncoming, SsaValueId,
};
pub use structure::IRStructDefinition;
pub use types::{
    ArrayType, BoolType, ClassRefType, ComplexType, DoubleType, EnumType, ExceptionEventType,
    FloatType, FunctionType, IRType, IntType, InterfaceType, ListType, MatrixType,
    MethodResultType, NullableType, StringType, StructType, VectorType, VoidType,
};
pub use value::{IRParameter, IRStorage, IRValue, LifecycleSource};
