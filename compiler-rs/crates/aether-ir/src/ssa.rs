//! Owned, schema-independent SSA representation and its schema-v2 boundary.
//!
//! Names are retained because schema-v2 uses them as stable identities.  The
//! newtypes below prevent accidentally interchanging function, block, and SSA
//! value identities in future CFG and renaming code.
#![allow(missing_docs)]

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use crate::wire::{
    IRInstructionDTO, IRStructDefinitionDTO, SSA_SCHEMA_VERSION_V2,
    SSABoundsCheckedInstructionV2DTO, SSAControlInstructionDTO, SSAInstructionDTO,
    SSAInstructionV2DTO, SSAModuleV2DTO, SSAPhiIncomingDTO,
};
use crate::{
    IRInstruction, IRParameter, IRStructDefinition, IRType, IRValue, import_instruction,
    import_parameter, import_struct_definition, import_type, import_value,
};

macro_rules! identity {
    ($name:ident) => {
        #[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);
        impl $name {
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self(value)
            }
        }
    };
}

identity!(FunctionId);
identity!(BlockId);
identity!(SsaValueId);

#[derive(Clone, Debug, PartialEq)]
pub struct PhiIncoming {
    pub predecessor: BlockId,
    pub value: IRValue,
}

/// An owned SSA instruction. Ordinary instructions are the existing owned IR
/// enum (not a wire DTO); SSA-only instructions have first-class payloads.
#[derive(Clone, Debug, PartialEq)]
pub enum OwnedSsaInstruction {
    Phi {
        result: IRValue,
        incoming: Vec<PhiIncoming>,
        wire: SSAControlInstructionDTO,
    },
    Control {
        wire: SSAControlInstructionDTO,
    },
    BoundsChecked {
        wire: SSABoundsCheckedInstructionV2DTO,
    },
    Ordinary {
        instruction: IRInstruction,
        wire: IRInstructionDTO,
    },
}

#[derive(Clone, Debug, PartialEq)]
pub struct OwnedSsaBlock {
    pub id: BlockId,
    pub instructions: Vec<OwnedSsaInstruction>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct OwnedSsaFunction {
    pub id: FunctionId,
    pub parameters: Vec<IRParameter>,
    pub return_type: IRType,
    pub blocks: Vec<OwnedSsaBlock>,
    pub entry_block: BlockId,
    pub may_throw: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct OwnedSsaModule {
    pub functions: Vec<OwnedSsaFunction>,
    pub structs: Vec<IRStructDefinition>,
    struct_wire: Vec<IRStructDefinitionDTO>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OwnedSsaCodecError {
    path: String,
    message: String,
}

impl OwnedSsaCodecError {
    fn new(path: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            message: message.into(),
        }
    }
}
impl fmt::Display for OwnedSsaCodecError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.path, self.message)
    }
}
impl Error for OwnedSsaCodecError {}

impl OwnedSsaModule {
    /// Decode and structurally validate a lossless schema-v2 DTO.
    #[allow(clippy::too_many_lines)]
    pub fn from_schema_v2(dto: &SSAModuleV2DTO) -> Result<Self, OwnedSsaCodecError> {
        if dto.schema_version != SSA_SCHEMA_VERSION_V2 {
            return Err(OwnedSsaCodecError::new(
                "schema_version",
                format!("unsupported SSA DTO schema version {}", dto.schema_version),
            ));
        }
        if dto.representation != "aether_ssa" {
            return Err(OwnedSsaCodecError::new(
                "representation",
                "expected aether_ssa",
            ));
        }
        let structs = dto
            .structs
            .iter()
            .enumerate()
            .map(|(i, value)| {
                import_struct_definition(value)
                    .map_err(|e| OwnedSsaCodecError::new(format!("structs[{i}]"), e.to_string()))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let functions = dto
            .functions
            .iter()
            .enumerate()
            .map(|(fi, function)| {
                let path = format!("functions[{fi}]");
                let parameters = function
                    .parameters
                    .iter()
                    .enumerate()
                    .map(|(i, value)| {
                        import_parameter(value).map_err(|e| {
                            OwnedSsaCodecError::new(
                                format!("{path}.parameters[{i}]"),
                                e.to_string(),
                            )
                        })
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                let return_type = import_type(&function.return_type).map_err(|e| {
                    OwnedSsaCodecError::new(format!("{path}.return_type"), e.to_string())
                })?;
                let mut block_names = BTreeSet::new();
                for block in &function.blocks {
                    if block.name.is_empty() {
                        return Err(OwnedSsaCodecError::new(
                            format!("{path}.blocks"),
                            "empty block identity",
                        ));
                    }
                    if !block_names.insert(block.name.clone()) {
                        return Err(OwnedSsaCodecError::new(
                            format!("{path}.blocks"),
                            format!("duplicate block identity {}", block.name),
                        ));
                    }
                }
                if !block_names.contains(&function.entry_block) {
                    return Err(OwnedSsaCodecError::new(
                        format!("{path}.entry_block"),
                        "target does not name a function block",
                    ));
                }
                let blocks = function
                    .blocks
                    .iter()
                    .enumerate()
                    .map(|(bi, block)| {
                        let instructions = block
                            .instructions
                            .iter()
                            .enumerate()
                            .map(|(ii, value)| {
                                decode_instruction(
                                    value,
                                    &block_names,
                                    format!("{path}.blocks[{bi}].instructions[{ii}]"),
                                )
                            })
                            .collect::<Result<Vec<_>, _>>()?;
                        Ok(OwnedSsaBlock {
                            id: block.name.clone().into(),
                            instructions,
                        })
                    })
                    .collect::<Result<Vec<_>, OwnedSsaCodecError>>()?;
                Ok(OwnedSsaFunction {
                    id: function.name.clone().into(),
                    parameters,
                    return_type,
                    blocks,
                    entry_block: function.entry_block.clone().into(),
                    may_throw: function.may_throw,
                })
            })
            .collect::<Result<Vec<_>, OwnedSsaCodecError>>()?;
        Ok(Self {
            functions,
            structs,
            struct_wire: dto.structs.clone(),
        })
    }

    /// Encode the owned model to the explicit schema-v2 wire contract.
    #[must_use]
    pub fn to_schema_v2(&self) -> SSAModuleV2DTO {
        SSAModuleV2DTO {
            schema_version: SSA_SCHEMA_VERSION_V2,
            representation: "aether_ssa".into(),
            functions: self
                .functions
                .iter()
                .map(|function| crate::wire::SSAFunctionV2DTO {
                    name: function.id.0.clone(),
                    parameters: function.parameters.iter().map(parameter_to_dto).collect(),
                    return_type: type_to_dto(&function.return_type),
                    blocks: function
                        .blocks
                        .iter()
                        .map(|block| crate::wire::SSABasicBlockV2DTO {
                            name: block.id.0.clone(),
                            instructions: block
                                .instructions
                                .iter()
                                .map(encode_instruction)
                                .collect(),
                        })
                        .collect(),
                    entry_block: function.entry_block.0.clone(),
                    may_throw: function.may_throw,
                })
                .collect(),
            structs: self.struct_wire.clone(),
        }
    }
}

#[allow(clippy::needless_pass_by_value)]
fn decode_instruction(
    value: &SSAInstructionV2DTO,
    blocks: &BTreeSet<String>,
    path: String,
) -> Result<OwnedSsaInstruction, OwnedSsaCodecError> {
    match value {
        SSAInstructionV2DTO::BoundsChecked(wire) => {
            Ok(OwnedSsaInstruction::BoundsChecked { wire: wire.clone() })
        }
        SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Ordinary(wire)) => {
            let instruction = import_instruction(wire)
                .map_err(|e| OwnedSsaCodecError::new(&path, e.to_string()))?;
            Ok(OwnedSsaInstruction::Ordinary {
                instruction,
                wire: wire.clone(),
            })
        }
        SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Control(
            wire @ SSAControlInstructionDTO::Phi { result, incoming },
        )) => {
            let result =
                import_value(result).map_err(|e| OwnedSsaCodecError::new(&path, e.to_string()))?;
            let incoming = incoming
                .iter()
                .enumerate()
                .map(|(i, item)| decode_phi(item, blocks, format!("{path}.incoming[{i}]")))
                .collect::<Result<_, _>>()?;
            Ok(OwnedSsaInstruction::Phi {
                result,
                incoming,
                wire: wire.clone(),
            })
        }
        SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Control(wire)) => {
            validate_control_targets(wire, blocks, &path)?;
            Ok(OwnedSsaInstruction::Control { wire: wire.clone() })
        }
    }
}

#[allow(clippy::needless_pass_by_value)]
fn decode_phi(
    item: &SSAPhiIncomingDTO,
    blocks: &BTreeSet<String>,
    path: String,
) -> Result<PhiIncoming, OwnedSsaCodecError> {
    if !blocks.contains(&item.block) {
        return Err(OwnedSsaCodecError::new(
            &path,
            "predecessor does not name a function block",
        ));
    }
    let value =
        import_value(&item.value).map_err(|e| OwnedSsaCodecError::new(&path, e.to_string()))?;
    Ok(PhiIncoming {
        predecessor: item.block.clone().into(),
        value,
    })
}

fn validate_control_targets(
    value: &SSAControlInstructionDTO,
    blocks: &BTreeSet<String>,
    path: &str,
) -> Result<(), OwnedSsaCodecError> {
    let targets: Vec<&String> = match value {
        SSAControlInstructionDTO::Invoke {
            normal_target,
            exceptional_target,
            ..
        }
        | SSAControlInstructionDTO::InvokeIndirect {
            normal_target,
            exceptional_target,
            ..
        }
        | SSAControlInstructionDTO::InvokeInterface {
            normal_target,
            exceptional_target,
            ..
        } => vec![normal_target, exceptional_target],
        SSAControlInstructionDTO::Throw { target, .. }
        | SSAControlInstructionDTO::Rethrow { target, .. }
        | SSAControlInstructionDTO::Propagate { target, .. } => target.0.iter().collect(),
        SSAControlInstructionDTO::Phi { .. } => Vec::new(),
    };
    if let Some(target) = targets.into_iter().find(|target| !blocks.contains(*target)) {
        return Err(OwnedSsaCodecError::new(
            path,
            format!("control target {target} does not name a function block"),
        ));
    }
    Ok(())
}

fn encode_instruction(value: &OwnedSsaInstruction) -> SSAInstructionV2DTO {
    match value {
        OwnedSsaInstruction::Phi { wire, .. } | OwnedSsaInstruction::Control { wire } => {
            SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Control(wire.clone()))
        }
        OwnedSsaInstruction::BoundsChecked { wire } => {
            SSAInstructionV2DTO::BoundsChecked(wire.clone())
        }
        OwnedSsaInstruction::Ordinary { wire, .. } => {
            SSAInstructionV2DTO::Unchanged(SSAInstructionDTO::Ordinary(wire.clone()))
        }
    }
}

fn parameter_to_dto(value: &IRParameter) -> crate::wire::IRParameterDTO {
    crate::wire::IRParameterDTO::Parameter {
        name: value.name.clone(),
        r#type: type_to_dto(&value.r#type),
    }
}

fn type_to_dto(value: &IRType) -> crate::wire::IRTypeDTO {
    use crate::wire::IRTypeDTO as D;
    match value {
        IRType::Int(_) => D::Int {},
        IRType::Float(_) => D::Float {},
        IRType::Double(_) => D::Double {},
        IRType::Bool(_) => D::Bool {},
        IRType::String(_) => D::String {},
        IRType::Void(_) => D::Void {},
        IRType::ExceptionEvent(_) => D::ExceptionEvent {},
        IRType::Complex(_) => D::Complex {},
        IRType::Function(v) => D::Function {
            parameter_types: v.parameter_types.iter().map(type_to_dto).collect(),
            return_type: Box::new(type_to_dto(&v.return_type)),
        },
        IRType::Nullable(v) => D::Nullable {
            inner: Box::new(type_to_dto(&v.inner)),
        },
        IRType::List(v) => D::List {
            element: Box::new(type_to_dto(&v.element)),
        },
        IRType::Array(v) => D::Array {
            element: Box::new(type_to_dto(&v.element)),
        },
        IRType::Vector(v) => D::Vector {
            element: Box::new(type_to_dto(&v.element)),
            orientation: crate::wire::NullableDTO(v.orientation.clone()),
        },
        IRType::Matrix(v) => D::Matrix {
            element: Box::new(type_to_dto(&v.element)),
        },
        IRType::Struct(v) => D::Struct {
            name: v.name.clone(),
        },
        IRType::MethodResult(v) => D::MethodResult {
            receiver: Box::new(D::Struct {
                name: v.receiver.name.clone(),
            }),
            value: Box::new(type_to_dto(&v.value)),
        },
        IRType::ClassRef(v) => D::ClassRef {
            name: v.name.clone(),
        },
        IRType::Interface(v) => D::Interface {
            name: v.name.clone(),
        },
        IRType::Enum(v) => D::Enum {
            name: v.name.clone(),
            variants: v.variants.clone(),
            display_name: crate::wire::NullableDTO(v.display_name.clone()),
        },
    }
}
