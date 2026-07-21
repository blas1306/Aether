//! Conversion from schema-v1 wire DTOs into the owned Rust IR.

use std::error::Error;
use std::fmt;

use crate::wire::{IRTypeDTO, NullableDTO};
use crate::{
    ArrayType, BoolType, ClassRefType, ComplexType, DoubleType, EnumType, FloatType, FunctionType,
    IRType, IntType, InterfaceType, ListType, MatrixType, MethodResultType, NullableType,
    StringType, StructType, VectorType, VoidType,
};

/// A structural failure while importing a wire DTO into the owned Rust IR.
///
/// Semantic validity is intentionally outside this error type and remains the
/// responsibility of the IR verifier.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IRImportError {
    /// A method-result receiver used a wire type that the owned IR cannot store.
    MethodResultReceiverNotStruct {
        /// Stable wire tag of the incompatible receiver type.
        actual: &'static str,
    },
}

impl fmt::Display for IRImportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MethodResultReceiverNotStruct { actual } => write!(
                formatter,
                "method-result receiver must be a struct type, found wire type '{actual}'"
            ),
        }
    }
}

impl Error for IRImportError {}

/// Reconstruct an owned Rust IR type from a borrowed wire DTO.
pub fn import_type(type_: &IRTypeDTO) -> Result<IRType, IRImportError> {
    type_.try_into()
}

impl TryFrom<IRTypeDTO> for IRType {
    type Error = IRImportError;

    fn try_from(type_: IRTypeDTO) -> Result<Self, Self::Error> {
        match type_ {
            IRTypeDTO::Int {} => Ok(IntType.into()),
            IRTypeDTO::Float {} => Ok(FloatType.into()),
            IRTypeDTO::Double {} => Ok(DoubleType.into()),
            IRTypeDTO::Bool {} => Ok(BoolType.into()),
            IRTypeDTO::String {} => Ok(StringType.into()),
            IRTypeDTO::Void {} => Ok(VoidType.into()),
            IRTypeDTO::Function {
                parameter_types,
                return_type,
            } => Ok(FunctionType {
                parameter_types: parameter_types
                    .into_iter()
                    .map(Self::try_from)
                    .collect::<Result<_, _>>()?,
                return_type: Box::new(Self::try_from(*return_type)?),
            }
            .into()),
            IRTypeDTO::Complex {} => Ok(ComplexType.into()),
            IRTypeDTO::Nullable { inner } => Ok(NullableType {
                inner: Box::new(Self::try_from(*inner)?),
            }
            .into()),
            IRTypeDTO::List { element } => Ok(ListType {
                element: Box::new(Self::try_from(*element)?),
            }
            .into()),
            IRTypeDTO::Array { element } => Ok(ArrayType {
                element: Box::new(Self::try_from(*element)?),
            }
            .into()),
            IRTypeDTO::Vector {
                element,
                orientation: NullableDTO(orientation),
            } => Ok(VectorType {
                element: Box::new(Self::try_from(*element)?),
                orientation,
            }
            .into()),
            IRTypeDTO::Matrix { element } => Ok(MatrixType {
                element: Box::new(Self::try_from(*element)?),
            }
            .into()),
            IRTypeDTO::Struct { name } => Ok(StructType { name }.into()),
            IRTypeDTO::MethodResult { receiver, value } => {
                let receiver = match *receiver {
                    IRTypeDTO::Struct { name } => StructType { name },
                    actual => {
                        return Err(IRImportError::MethodResultReceiverNotStruct {
                            actual: wire_type_tag(&actual),
                        });
                    }
                };
                Ok(MethodResultType {
                    receiver,
                    value: Box::new(Self::try_from(*value)?),
                }
                .into())
            }
            IRTypeDTO::ClassRef { name } => Ok(ClassRefType { name }.into()),
            IRTypeDTO::Interface { name } => Ok(InterfaceType { name }.into()),
            IRTypeDTO::Enum {
                name,
                variants,
                display_name: NullableDTO(display_name),
            } => Ok(EnumType {
                name,
                variants,
                display_name,
            }
            .into()),
        }
    }
}

impl TryFrom<&IRTypeDTO> for IRType {
    type Error = IRImportError;

    fn try_from(type_: &IRTypeDTO) -> Result<Self, Self::Error> {
        Self::try_from(type_.clone())
    }
}

const fn wire_type_tag(type_: &IRTypeDTO) -> &'static str {
    match type_ {
        IRTypeDTO::Int {} => "int",
        IRTypeDTO::Float {} => "float",
        IRTypeDTO::Double {} => "double",
        IRTypeDTO::Bool {} => "bool",
        IRTypeDTO::String {} => "string",
        IRTypeDTO::Void {} => "void",
        IRTypeDTO::Function { .. } => "function",
        IRTypeDTO::Complex {} => "complex",
        IRTypeDTO::Nullable { .. } => "nullable",
        IRTypeDTO::List { .. } => "list",
        IRTypeDTO::Array { .. } => "array",
        IRTypeDTO::Vector { .. } => "vector",
        IRTypeDTO::Matrix { .. } => "matrix",
        IRTypeDTO::Struct { .. } => "struct",
        IRTypeDTO::MethodResult { .. } => "method_result",
        IRTypeDTO::ClassRef { .. } => "class_ref",
        IRTypeDTO::Interface { .. } => "interface",
        IRTypeDTO::Enum { .. } => "enum",
    }
}
