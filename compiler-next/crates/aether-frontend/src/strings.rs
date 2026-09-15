//! Explicit semantic operations for the GENERAL-V1 immutable string owner.
#![allow(missing_docs)]

use crate::{Span, TypeArena, TypeData, TypeId};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InterpolationConversion {
    StringBorrow,
    CanonicalScalarFormat,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StringOwnership {
    Fresh,
    /// Invalid at the FORMAT-V1 boundary; retained so corrupted IR is representable and rejectable.
    Borrowed,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InterpolationSizePlan {
    CheckedExact,
    /// Invalid at the FORMAT-V1 boundary; retained for independent verifier qualification.
    Unchecked,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InterpolationFragment<O> {
    Text {
        bytes: Vec<u8>,
        span: Span,
    },
    Hole {
        value: O,
        ty: TypeId,
        conversion: InterpolationConversion,
        span: Span,
    },
}

/// String operations retained through HIR, MIR and SSA. Operands are borrowed
/// unless `Alias` explicitly creates a second logical owner.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StringOp<O> {
    Literal {
        bytes: Vec<u8>,
    },
    Alias {
        source: O,
    },
    Concat {
        left: O,
        right: O,
    },
    Equal {
        left: O,
        right: O,
        negate: bool,
    },
    ByteLength {
        source: O,
    },
    Output {
        source: O,
        newline: bool,
    },
    Interpolate {
        fragments: Vec<InterpolationFragment<O>>,
        ownership: StringOwnership,
        size_plan: InterpolationSizePlan,
    },
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
            Self::Interpolate { fragments, .. } => fragments
                .iter()
                .filter_map(|fragment| match fragment {
                    InterpolationFragment::Hole { value, .. } => Some(value),
                    InterpolationFragment::Text { .. } => None,
                })
                .collect(),
        }
    }

    #[must_use]
    pub const fn creates_owner(&self) -> bool {
        matches!(
            self,
            Self::Literal { .. }
                | Self::Alias { .. }
                | Self::Concat { .. }
                | Self::Interpolate { .. }
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
            Self::Interpolate {
                fragments,
                ownership,
                size_plan,
            } => StringOp::Interpolate {
                fragments: fragments
                    .into_iter()
                    .map(|fragment| {
                        Ok(match fragment {
                            InterpolationFragment::Text { bytes, span } => {
                                InterpolationFragment::Text { bytes, span }
                            }
                            InterpolationFragment::Hole {
                                value,
                                ty,
                                conversion,
                                span,
                            } => InterpolationFragment::Hole {
                                value: f(value)?,
                                ty,
                                conversion,
                                span,
                            },
                        })
                    })
                    .collect::<Result<Vec<_>, E>>()?,
                ownership,
                size_plan,
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
    if !matches!(op, StringOp::Interpolate { .. }) {
        for operand in op.operands() {
            if operand_ty(operand)? != TypeId::STRING {
                return Err("string operation operand is not string".into());
            }
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
        StringOp::Interpolate {
            fragments,
            ownership,
            size_plan,
        } => {
            if *ownership != StringOwnership::Fresh
                || *size_plan != InterpolationSizePlan::CheckedExact
            {
                return Err("interpolation ownership or size plan is invalid".into());
            }
            let mut previous_end = None;
            for fragment in fragments {
                let span = match fragment {
                    InterpolationFragment::Text { span, .. }
                    | InterpolationFragment::Hole { span, .. } => *span,
                };
                if previous_end.is_some_and(|end| span.start < end) {
                    return Err("interpolation fragments are reordered or overlapping".into());
                }
                previous_end = Some(span.end);
                match fragment {
                    InterpolationFragment::Text { bytes, .. } => {
                        std::str::from_utf8(bytes)
                            .map_err(|_| "interpolation text is not UTF-8")?;
                    }
                    InterpolationFragment::Hole {
                        value,
                        ty,
                        conversion,
                        ..
                    } => {
                        if operand_ty(value)? != *ty {
                            return Err(
                                "interpolation hole TypeId disagrees with its operand".into()
                            );
                        }
                        let expected = if *ty == TypeId::STRING {
                            InterpolationConversion::StringBorrow
                        } else if matches!(
                            types.get(*ty),
                            Some(
                                TypeData::Bool
                                    | TypeData::Char
                                    | TypeData::Integer(_)
                                    | TypeData::Float(_)
                            )
                        ) {
                            InterpolationConversion::CanonicalScalarFormat
                        } else {
                            return Err("interpolation hole has an unsupported type".into());
                        };
                        if *conversion != expected {
                            return Err("interpolation conversion kind is invalid".into());
                        }
                    }
                }
            }
            TypeId::STRING
        }
    };
    if result != expected {
        return Err("string operation result type is invalid".into());
    }
    Ok(())
}
