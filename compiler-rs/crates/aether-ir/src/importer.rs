//! Conversion from schema-v1 wire DTOs into the owned Rust IR.

use std::error::Error;
use std::fmt;

use crate::wire::{
    IRConstantDTO, IREnumConstantDTO, IRParameterDTO, IRSourceLocationDTO, IRStorageDTO, IRTypeDTO,
    IRValueDTO, NullableDTO,
};
use crate::{
    ArrayType, BoolType, ClassRefType, ComplexType, DoubleType, EnumType, FloatType, FunctionType,
    IRConstant, IREnumConstant, IRParameter, IRSourceLocation, IRStorage, IRType, IRValue, IntType,
    InterfaceType, ListType, MatrixType, MethodResultType, NullableType, StringType, StructType,
    VectorType, VoidType,
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
    /// A named value's `type` field could not be represented by the owned IR.
    ValueType {
        /// Stable tag of the wire value variant being imported.
        kind: &'static str,
        /// Structural type-import failure.
        source: Box<Self>,
    },
    /// A storage entity's `type` field could not be represented by the owned IR.
    StorageType {
        /// Structural type-import failure.
        source: Box<Self>,
    },
    /// A parameter entity's `type` field could not be represented by the owned IR.
    ParameterType {
        /// Structural type-import failure.
        source: Box<Self>,
    },
    /// A constant floating-point field was not finite.
    NonFiniteConstantFloat {
        /// Stable field name within the constant DTO variant.
        field: &'static str,
    },
}

impl fmt::Display for IRImportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MethodResultReceiverNotStruct { actual } => write!(
                formatter,
                "method-result receiver must be a struct type, found wire type '{actual}'"
            ),
            Self::ValueType { kind, source } => write!(
                formatter,
                "value DTO variant '{kind}' field 'type' could not be imported: {source}"
            ),
            Self::StorageType { source } => write!(
                formatter,
                "storage DTO field 'type' could not be imported: {source}"
            ),
            Self::ParameterType { source } => write!(
                formatter,
                "parameter DTO field 'type' could not be imported: {source}"
            ),
            Self::NonFiniteConstantFloat { field } => write!(
                formatter,
                "constant DTO field '{field}' must contain a finite floating-point value"
            ),
        }
    }
}

impl Error for IRImportError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::ValueType { source, .. }
            | Self::StorageType { source }
            | Self::ParameterType { source } => Some(source),
            Self::MethodResultReceiverNotStruct { .. } | Self::NonFiniteConstantFloat { .. } => {
                None
            }
        }
    }
}

/// Reconstruct an owned Rust IR type from a borrowed wire DTO.
pub fn import_type(type_: &IRTypeDTO) -> Result<IRType, IRImportError> {
    type_.try_into()
}

/// Reconstruct an owned Rust IR enum constant from a borrowed wire DTO.
pub fn import_enum_constant(constant: &IREnumConstantDTO) -> Result<IREnumConstant, IRImportError> {
    constant.try_into()
}

/// Reconstruct an owned Rust IR constant from a borrowed wire DTO.
pub fn import_constant(constant: &IRConstantDTO) -> Result<IRConstant, IRImportError> {
    constant.try_into()
}

/// Reconstruct an owned Rust IR value from a borrowed wire DTO.
pub fn import_value(value: &IRValueDTO) -> Result<IRValue, IRImportError> {
    value.try_into()
}

/// Reconstruct an owned Rust IR storage location from a borrowed wire DTO.
pub fn import_storage(storage: &IRStorageDTO) -> Result<IRStorage, IRImportError> {
    storage.try_into()
}

/// Reconstruct an owned Rust IR parameter from a borrowed wire DTO.
pub fn import_parameter(parameter: &IRParameterDTO) -> Result<IRParameter, IRImportError> {
    parameter.try_into()
}

/// Reconstruct an owned Rust source location from a borrowed wire DTO.
pub fn import_source_location(
    source_location: &IRSourceLocationDTO,
) -> Result<IRSourceLocation, IRImportError> {
    source_location.try_into()
}

/// Reconstruct an optional owned Rust source location from a nullable wire field.
pub fn import_optional_source_location(
    source_location: &NullableDTO<IRSourceLocationDTO>,
) -> Result<Option<IRSourceLocation>, IRImportError> {
    source_location
        .0
        .as_ref()
        .map(IRSourceLocation::try_from)
        .transpose()
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

impl TryFrom<IREnumConstantDTO> for IREnumConstant {
    type Error = IRImportError;

    fn try_from(constant: IREnumConstantDTO) -> Result<Self, Self::Error> {
        let IREnumConstantDTO::EnumConstant {
            enum_name,
            member_name,
            member_id,
            discriminant,
        } = constant;

        Ok(Self {
            enum_name,
            member_name,
            member_id,
            discriminant,
        })
    }
}

impl TryFrom<&IREnumConstantDTO> for IREnumConstant {
    type Error = IRImportError;

    fn try_from(constant: &IREnumConstantDTO) -> Result<Self, Self::Error> {
        Self::try_from(constant.clone())
    }
}

impl TryFrom<IRConstantDTO> for IRConstant {
    type Error = IRImportError;

    fn try_from(constant: IRConstantDTO) -> Result<Self, Self::Error> {
        match constant {
            IRConstantDTO::Bool { value } => Ok(Self::Bool(value)),
            IRConstantDTO::Int { value } => Ok(Self::Int(value)),
            IRConstantDTO::Float { value } => {
                Ok(Self::Float(import_finite_constant_float(value.0, "value")?))
            }
            IRConstantDTO::Complex { real, imaginary } => Ok(Self::Complex {
                real: import_finite_constant_float(real.0, "real")?,
                imaginary: import_finite_constant_float(imaginary.0, "imaginary")?,
            }),
            IRConstantDTO::String { value } => Ok(Self::String(value)),
            IRConstantDTO::Enum { value } => Ok(Self::Enum(value.try_into()?)),
        }
    }
}

impl TryFrom<&IRConstantDTO> for IRConstant {
    type Error = IRImportError;

    fn try_from(constant: &IRConstantDTO) -> Result<Self, Self::Error> {
        Self::try_from(constant.clone())
    }
}

impl TryFrom<IRValueDTO> for IRValue {
    type Error = IRImportError;

    fn try_from(value: IRValueDTO) -> Result<Self, Self::Error> {
        let (kind, name, type_) = match value {
            IRValueDTO::Value { name, r#type } => ("value", name, r#type),
            IRValueDTO::Storage { name, r#type } => ("storage", name, r#type),
            IRValueDTO::Parameter { name, r#type } => ("parameter", name, r#type),
        };
        let r#type = IRType::try_from(type_).map_err(|source| IRImportError::ValueType {
            kind,
            source: Box::new(source),
        })?;

        Ok(Self { name, r#type })
    }
}

impl TryFrom<&IRValueDTO> for IRValue {
    type Error = IRImportError;

    fn try_from(value: &IRValueDTO) -> Result<Self, Self::Error> {
        Self::try_from(value.clone())
    }
}

impl TryFrom<IRStorageDTO> for IRStorage {
    type Error = IRImportError;

    fn try_from(storage: IRStorageDTO) -> Result<Self, Self::Error> {
        let IRStorageDTO::Storage { name, r#type } = storage;
        let r#type = IRType::try_from(r#type).map_err(|source| IRImportError::StorageType {
            source: Box::new(source),
        })?;

        Ok(Self { name, r#type })
    }
}

impl TryFrom<&IRStorageDTO> for IRStorage {
    type Error = IRImportError;

    fn try_from(storage: &IRStorageDTO) -> Result<Self, Self::Error> {
        Self::try_from(storage.clone())
    }
}

impl TryFrom<IRParameterDTO> for IRParameter {
    type Error = IRImportError;

    fn try_from(parameter: IRParameterDTO) -> Result<Self, Self::Error> {
        let IRParameterDTO::Parameter { name, r#type } = parameter;
        let r#type = IRType::try_from(r#type).map_err(|source| IRImportError::ParameterType {
            source: Box::new(source),
        })?;

        Ok(Self { name, r#type })
    }
}

impl TryFrom<&IRParameterDTO> for IRParameter {
    type Error = IRImportError;

    fn try_from(parameter: &IRParameterDTO) -> Result<Self, Self::Error> {
        Self::try_from(parameter.clone())
    }
}

impl TryFrom<IRSourceLocationDTO> for IRSourceLocation {
    type Error = IRImportError;

    fn try_from(source_location: IRSourceLocationDTO) -> Result<Self, Self::Error> {
        let IRSourceLocationDTO::SourceLocation {
            line,
            column,
            path: NullableDTO(path),
        } = source_location;

        Ok(Self { line, column, path })
    }
}

impl TryFrom<&IRSourceLocationDTO> for IRSourceLocation {
    type Error = IRImportError;

    fn try_from(source_location: &IRSourceLocationDTO) -> Result<Self, Self::Error> {
        Self::try_from(source_location.clone())
    }
}

fn import_finite_constant_float(value: f64, field: &'static str) -> Result<f64, IRImportError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(IRImportError::NonFiniteConstantFloat { field })
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
