//! Canonical scalar types and the minimal admitted target model.
#![allow(missing_docs)]

use std::fmt;

/// Properties that affect source-level scalar layout.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TargetProperties {
    /// Width of pointers and architecture-sized integers.
    pub pointer_width: u16,
}

impl TargetProperties {
    /// The only target admitted by the bootstrap compiler.
    pub const LINUX_X86_64: Self = Self { pointer_width: 64 };
}

/// Canonical integer types. Architecture-sized types remain distinct from
/// fixed-width types even when their physical widths happen to match.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IntegerType {
    Int8,
    Int16,
    Int32,
    Int64,
    Uint8,
    Uint16,
    Uint32,
    Uint64,
    Isize,
    Usize,
}

impl IntegerType {
    #[must_use]
    pub const fn is_signed(self) -> bool {
        matches!(
            self,
            Self::Int8 | Self::Int16 | Self::Int32 | Self::Int64 | Self::Isize
        )
    }

    #[must_use]
    pub const fn bits(self, target: TargetProperties) -> u16 {
        match self {
            Self::Int8 | Self::Uint8 => 8,
            Self::Int16 | Self::Uint16 => 16,
            Self::Int32 | Self::Uint32 => 32,
            Self::Int64 | Self::Uint64 => 64,
            Self::Isize | Self::Usize => target.pointer_width,
        }
    }

    #[must_use]
    pub fn range(self, target: TargetProperties) -> (i128, i128) {
        let bits = u32::from(self.bits(target));
        if self.is_signed() {
            (-(1_i128 << (bits - 1)), (1_i128 << (bits - 1)) - 1)
        } else {
            (0, (1_i128 << bits) - 1)
        }
    }

    #[must_use]
    pub const fn can_widen_to(self, to: Self) -> bool {
        use IntegerType::{Int8, Int16, Int32, Int64, Uint8, Uint16, Uint32, Uint64};
        matches!(
            (self, to),
            (Int8, Int16 | Int32 | Int64)
                | (Int16, Int32 | Int64)
                | (Int32, Int64)
                | (Uint8, Uint16 | Uint32 | Uint64)
                | (Uint16, Uint32 | Uint64)
                | (Uint32, Uint64)
        )
    }
}

impl fmt::Display for IntegerType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Int8 => "int8",
            Self::Int16 => "int16",
            Self::Int32 => "int32",
            Self::Int64 => "int64",
            Self::Uint8 => "uint8",
            Self::Uint16 => "uint16",
            Self::Uint32 => "uint32",
            Self::Uint64 => "uint64",
            Self::Isize => "isize",
            Self::Usize => "usize",
        })
    }
}

/// Canonical IEEE-754 scalar formats.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FloatType {
    Float32,
    Float64,
}

impl fmt::Display for FloatType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Float32 => "float32",
            Self::Float64 => "float64",
        })
    }
}

/// Canonical semantic types. Composite and generic variants can extend this
/// enum; a `TypeId` interner is deferred until recursive types justify one.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Type {
    Bool,
    Integer(IntegerType),
    Float(FloatType),
}

impl Type {
    pub const INT64: Self = Self::Integer(IntegerType::Int64);
    #[must_use]
    pub const fn as_integer(self) -> Option<IntegerType> {
        if let Self::Integer(v) = self {
            Some(v)
        } else {
            None
        }
    }
    #[must_use]
    pub const fn as_float(self) -> Option<FloatType> {
        if let Self::Float(v) = self {
            Some(v)
        } else {
            None
        }
    }
    #[must_use]
    pub const fn is_numeric(self) -> bool {
        !matches!(self, Self::Bool)
    }
}

impl fmt::Display for Type {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Bool => f.write_str("bool"),
            Self::Integer(v) => v.fmt(f),
            Self::Float(v) => v.fmt(f),
        }
    }
}
