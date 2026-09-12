//! Explicit semantic operations for the GENERAL-V1 immutable string owner.
#![allow(missing_docs)]

use crate::{TypeArena, TypeId};

/// String operations retained through HIR, MIR and SSA. Operands are borrowed
/// unless `Alias` explicitly creates a second logical owner.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StringOp<O> {
    Literal { bytes: Vec<u8> },
    Alias { source: O },
    Concat { left: O, right: O },
    Equal { left: O, right: O, negate: bool },
    ByteLength { source: O },
    Output { source: O, newline: bool },
}

impl<O> StringOp<O> {
    #[must_use]
    pub fn operands(&self) -> Vec<&O> {
        match self {
            Self::Literal { .. } => Vec::new(),
            Self::Alias { source } | Self::ByteLength { source } | Self::Output { source, .. } => {
                vec![source]
            }
            Self::Concat { left, right } | Self::Equal { left, right, .. } => {
                vec![left, right]
            }
        }
    }

    #[must_use]
    pub const fn creates_owner(&self) -> bool {
        matches!(
            self,
            Self::Literal { .. } | Self::Alias { .. } | Self::Concat { .. }
        )
    }

    pub fn map<P, E>(self, mut f: impl FnMut(O) -> Result<P, E>) -> Result<StringOp<P>, E> {
        Ok(match self {
            Self::Literal { bytes } => StringOp::Literal { bytes },
            Self::Alias { source } => StringOp::Alias { source: f(source)? },
            Self::Concat { left, right } => StringOp::Concat {
                left: f(left)?,
                right: f(right)?,
            },
            Self::Equal {
                left,
                right,
                negate,
            } => StringOp::Equal {
                left: f(left)?,
                right: f(right)?,
                negate,
            },
            Self::ByteLength { source } => StringOp::ByteLength { source: f(source)? },
            Self::Output { source, newline } => StringOp::Output {
                source: f(source)?,
                newline,
            },
        })
    }
}

/// Reconstructs the closed type/effect contract at each IR boundary.
pub fn verify_string_op<O>(
    op: &StringOp<O>,
    result: TypeId,
    types: &TypeArena,
    operand_ty: impl Fn(&O) -> Result<TypeId, String>,
) -> Result<(), String> {
    if types.get(TypeId::STRING) != Some(&crate::TypeData::String) {
        return Err("canonical string type metadata is missing".into());
    }
    for operand in op.operands() {
        if operand_ty(operand)? != TypeId::STRING {
            return Err("string operation operand is not string".into());
        }
    }
    let expected = match op {
        StringOp::Literal { bytes } => {
            std::str::from_utf8(bytes).map_err(|_| "string literal metadata is not UTF-8")?;
            TypeId::STRING
        }
        StringOp::Alias { .. } | StringOp::Concat { .. } => TypeId::STRING,
        StringOp::Equal { .. } | StringOp::Output { .. } => TypeId::BOOL,
        StringOp::ByteLength { .. } => TypeId::USIZE,
    };
    if result != expected {
        return Err("string operation result type is invalid".into());
    }
    Ok(())
}
