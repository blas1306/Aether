//! Semantic operations for the canonical `std::Text` module.
#![allow(missing_docs)]

use crate::{EnumInfo, StructInfo, TypeArena, TypeData, TypeId};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TextOp<O> {
    CodePointCount {
        value: O,
    },
    Contains {
        value: O,
        needle: O,
    },
    StartsWith {
        value: O,
        prefix: O,
    },
    EndsWith {
        value: O,
        suffix: O,
    },
    Find {
        value: O,
        needle: O,
        start: Option<O>,
    },
    Substring {
        value: O,
        start: O,
        end: O,
    },
    Trim {
        value: O,
    },
    Split {
        value: O,
        separator: O,
    },
}

impl<O> TextOp<O> {
    #[must_use]
    pub fn operands(&self) -> Vec<&O> {
        match self {
            Self::CodePointCount { value } | Self::Trim { value } => vec![value],
            Self::Contains { value, needle }
            | Self::Find {
                value,
                needle,
                start: None,
            }
            | Self::Split {
                value,
                separator: needle,
            } => vec![value, needle],
            Self::StartsWith { value, prefix } => vec![value, prefix],
            Self::EndsWith { value, suffix } => vec![value, suffix],
            Self::Find {
                value,
                needle,
                start: Some(start),
            } => vec![value, needle, start],
            Self::Substring { value, start, end } => vec![value, start, end],
        }
    }

    #[must_use]
    pub const fn creates_owner(&self) -> bool {
        matches!(
            self,
            Self::Substring { .. } | Self::Trim { .. } | Self::Split { .. }
        )
    }

    pub fn map<P, E>(self, mut f: impl FnMut(O) -> Result<P, E>) -> Result<TextOp<P>, E> {
        Ok(match self {
            Self::CodePointCount { value } => TextOp::CodePointCount { value: f(value)? },
            Self::Contains { value, needle } => TextOp::Contains {
                value: f(value)?,
                needle: f(needle)?,
            },
            Self::StartsWith { value, prefix } => TextOp::StartsWith {
                value: f(value)?,
                prefix: f(prefix)?,
            },
            Self::EndsWith { value, suffix } => TextOp::EndsWith {
                value: f(value)?,
                suffix: f(suffix)?,
            },
            Self::Find {
                value,
                needle,
                start,
            } => TextOp::Find {
                value: f(value)?,
                needle: f(needle)?,
                start: start.map(&mut f).transpose()?,
            },
            Self::Substring { value, start, end } => TextOp::Substring {
                value: f(value)?,
                start: f(start)?,
                end: f(end)?,
            },
            Self::Trim { value } => TextOp::Trim { value: f(value)? },
            Self::Split { value, separator } => TextOp::Split {
                value: f(value)?,
                separator: f(separator)?,
            },
        })
    }
}

pub fn verify_text_op<O>(
    op: &TextOp<O>,
    result: TypeId,
    types: &TypeArena,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    operand_ty: impl Fn(&O) -> Result<TypeId, String>,
) -> Result<(), String> {
    let scalar = structs
        .iter()
        .find(|s| s.name == "ScalarOffset" && s.module.0 != 0)
        .ok_or("canonical Text.ScalarOffset metadata is missing")?;
    let scalar_ty = types
        .entries()
        .find_map(|(ty, data)| {
            matches!(data, TypeData::Struct(id) if *id == scalar.id).then_some(ty)
        })
        .ok_or("canonical Text.ScalarOffset type is missing")?;
    let find = enums
        .iter()
        .find(|e| e.name == "FindResult" && e.module == scalar.module)
        .ok_or("canonical Text.FindResult metadata is missing")?;
    let find_ty = types
        .entries()
        .find_map(|(ty, data)| matches!(data, TypeData::Enum(id) if *id == find.id).then_some(ty))
        .ok_or("canonical Text.FindResult type is missing")?;

    let tys = op
        .operands()
        .into_iter()
        .map(&operand_ty)
        .collect::<Result<Vec<_>, _>>()?;
    let (string_count, expected) = match op {
        TextOp::CodePointCount { .. } => (1, TypeId::USIZE),
        TextOp::Contains { .. } | TextOp::StartsWith { .. } | TextOp::EndsWith { .. } => {
            (2, TypeId::BOOL)
        }
        TextOp::Find { start: None, .. } | TextOp::Find { start: Some(_), .. } => (2, find_ty),
        TextOp::Substring { .. } | TextOp::Trim { .. } => (1, TypeId::STRING),
        TextOp::Split { .. } => (
            2,
            types
                .entries()
                .find_map(|(ty, data)| {
                    matches!(data, TypeData::List { element } if *element == TypeId::STRING)
                        .then_some(ty)
                })
                .ok_or("canonical List<string> type is missing")?,
        ),
    };
    if tys
        .iter()
        .take(string_count)
        .any(|ty| *ty != TypeId::STRING)
        || tys.iter().skip(string_count).any(|ty| *ty != scalar_ty)
    {
        return Err("Text operation operand type is invalid".into());
    }
    if result != expected {
        return Err("Text operation result type is invalid".into());
    }
    Ok(())
}
