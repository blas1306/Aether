//! Canonical semantic types and the minimal admitted target model.
#![allow(missing_docs)]

use std::collections::HashMap;
use std::fmt;

/// Session-local nominal identity of a source `struct` declaration.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StructId(pub u32);

/// Session-local nominal identity of a source `enum` declaration.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EnumId(pub u32);

/// Session-local semantic identity of one enum variant. Variant names are
/// metadata after HIR resolution.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct VariantId {
    /// Owning nominal enum identity.
    pub enum_id: EnumId,
    /// Declaration-order index within the owner.
    pub index: u32,
}

/// Session-local identity of a field declaration. Field names are metadata
/// after HIR resolution; this identity is authoritative below the frontend.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FieldId(pub u32);

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

/// Compact identity of a canonical semantic type in one compilation session.
///
/// The numeric value is neither persistent nor an ABI identity.  It is only
/// meaningful together with the [`TypeArena`] that created it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TypeId(pub u32);

impl TypeId {
    /// Deterministic IDs for the baseline scalar set.  These constants are a
    /// construction convenience; consumers must still query/validate through
    /// the session arena and must not interpret their numeric values.
    pub const BOOL: Self = Self(0);
    pub const INT8: Self = Self(1);
    pub const INT16: Self = Self(2);
    pub const INT32: Self = Self(3);
    pub const INT64: Self = Self(4);
    pub const UINT8: Self = Self(5);
    pub const UINT16: Self = Self(6);
    pub const UINT32: Self = Self(7);
    pub const UINT64: Self = Self(8);
    pub const ISIZE: Self = Self(9);
    pub const USIZE: Self = Self(10);
    pub const FLOAT32: Self = Self(11);
    pub const FLOAT64: Self = Self(12);
}

impl fmt::Display for TypeId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Source diagnostics are normally formatted through TypeArena.  This
        // fallback keeps scalar-only low-level errors readable and makes a
        // missing context conspicuous for nominal/invalid identities.
        let spelling = match *self {
            Self::BOOL => "bool",
            Self::INT8 => "int8",
            Self::INT16 => "int16",
            Self::INT32 => "int32",
            Self::INT64 => "int64",
            Self::UINT8 => "uint8",
            Self::UINT16 => "uint16",
            Self::UINT32 => "uint32",
            Self::UINT64 => "uint64",
            Self::ISIZE => "isize",
            Self::USIZE => "usize",
            Self::FLOAT32 => "float32",
            Self::FLOAT64 => "float64",
            Self(_) => return write!(f, "TypeId({})", self.0),
        };
        f.write_str(spelling)
    }
}

/// Data stored once for each canonical semantic type.
///
/// Nominal aggregate variants contain declaration identity, so equal-layout
/// declarations remain different types. Transparent aliases deliberately do
/// not have a variant here.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TypeData {
    Bool,
    Integer(IntegerType),
    Float(FloatType),
    /// Nominal, module-owned value aggregate.
    Struct(StructId),
    /// Nominal, module-owned tagged value aggregate.
    Enum(EnumId),
}

impl TypeData {
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
        matches!(self, Self::Integer(_) | Self::Float(_))
    }
    #[must_use]
    pub const fn as_struct(self) -> Option<StructId> {
        if let Self::Struct(id) = self {
            Some(id)
        } else {
            None
        }
    }
    #[must_use]
    pub const fn as_enum(self) -> Option<EnumId> {
        if let Self::Enum(id) = self {
            Some(id)
        } else {
            None
        }
    }
}

impl fmt::Display for TypeData {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Bool => f.write_str("bool"),
            Self::Integer(v) => v.fmt(f),
            Self::Float(v) => v.fmt(f),
            Self::Struct(id) => write!(f, "struct#{}", id.0),
            Self::Enum(id) => write!(f, "enum#{}", id.0),
        }
    }
}

/// Session-owned bidirectional canonical type table.
///
/// The arena has ordinary Rust ownership, contains no global state and can be
/// cloned only when an unverified IR is deliberately cloned by tests/tools.
/// Production phase transitions move it forward with the program context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypeArena {
    data: Vec<TypeData>,
    ids: HashMap<TypeData, TypeId>,
}

impl Default for TypeArena {
    fn default() -> Self {
        Self::new()
    }
}

impl TypeArena {
    /// Creates an arena with the complete scalar baseline interned in a stable
    /// order so same-source debugging dumps remain deterministic.
    #[must_use]
    pub fn new() -> Self {
        let mut arena = Self {
            data: Vec::new(),
            ids: HashMap::new(),
        };
        let baseline = [
            TypeData::Bool,
            TypeData::Integer(IntegerType::Int8),
            TypeData::Integer(IntegerType::Int16),
            TypeData::Integer(IntegerType::Int32),
            TypeData::Integer(IntegerType::Int64),
            TypeData::Integer(IntegerType::Uint8),
            TypeData::Integer(IntegerType::Uint16),
            TypeData::Integer(IntegerType::Uint32),
            TypeData::Integer(IntegerType::Uint64),
            TypeData::Integer(IntegerType::Isize),
            TypeData::Integer(IntegerType::Usize),
            TypeData::Float(FloatType::Float32),
            TypeData::Float(FloatType::Float64),
        ];
        for (expected, data) in baseline.into_iter().enumerate() {
            let id = arena.intern(data);
            debug_assert_eq!(id.0 as usize, expected);
        }
        arena
    }

    /// Returns the existing canonical identity or inserts one new entry.
    pub fn intern(&mut self, data: TypeData) -> TypeId {
        if let Some(id) = self.ids.get(&data) {
            return *id;
        }
        let id = TypeId(u32::try_from(self.data.len()).expect("type arena fits in u32"));
        self.data.push(data);
        self.ids.insert(data, id);
        id
    }

    /// Looks up an identity, failing closed for an ID from another/malformed
    /// session instead of indexing unchecked.
    #[must_use]
    pub fn get(&self, id: TypeId) -> Option<&TypeData> {
        self.data.get(id.0 as usize)
    }

    /// Finds the canonical identity already assigned to `data`.
    #[must_use]
    pub fn id_of(&self, data: TypeData) -> Option<TypeId> {
        self.ids.get(&data).copied()
    }

    #[must_use]
    pub fn is_valid(&self, id: TypeId) -> bool {
        self.get(id).is_some()
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.data.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }

    #[must_use]
    pub fn integer_info(&self, id: TypeId) -> Option<IntegerType> {
        match self.get(id) {
            Some(TypeData::Integer(value)) => Some(*value),
            _ => None,
        }
    }

    #[must_use]
    pub fn float_info(&self, id: TypeId) -> Option<FloatType> {
        match self.get(id) {
            Some(TypeData::Float(value)) => Some(*value),
            _ => None,
        }
    }

    #[must_use]
    pub fn is_numeric(&self, id: TypeId) -> bool {
        matches!(
            self.get(id),
            Some(TypeData::Integer(_) | TypeData::Float(_))
        )
    }

    #[must_use]
    pub fn struct_id(&self, id: TypeId) -> Option<StructId> {
        match self.get(id) {
            Some(TypeData::Struct(value)) => Some(*value),
            _ => None,
        }
    }

    #[must_use]
    pub fn enum_id(&self, id: TypeId) -> Option<EnumId> {
        match self.get(id) {
            Some(TypeData::Enum(value)) => Some(*value),
            _ => None,
        }
    }

    /// Readable canonical spelling for diagnostics and deterministic dumps.
    #[must_use]
    pub fn format(&self, id: TypeId) -> String {
        self.get(id).map_or_else(
            || format!("<invalid TypeId({})>", id.0),
            ToString::to_string,
        )
    }

    /// Deterministic debug view in allocation order.
    pub fn entries(&self) -> impl Iterator<Item = (TypeId, &TypeData)> {
        self.data.iter().enumerate().map(|(index, data)| {
            (
                TypeId(u32::try_from(index).expect("type arena index fits u32")),
                data,
            )
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn baseline_is_canonical_and_target_sized_types_remain_distinct() {
        let mut types = TypeArena::new();
        assert_eq!(types.intern(TypeData::Bool), TypeId::BOOL);
        assert_eq!(
            types.intern(TypeData::Integer(IntegerType::Int64)),
            TypeId::INT64
        );
        assert_eq!(
            types.intern(TypeData::Float(FloatType::Float32)),
            TypeId::FLOAT32
        );
        assert_ne!(TypeId::ISIZE, TypeId::INT64);
        assert_ne!(TypeId::USIZE, TypeId::UINT64);
        assert_eq!(types.integer_info(TypeId::ISIZE), Some(IntegerType::Isize));
        assert_eq!(types.integer_info(TypeId::USIZE), Some(IntegerType::Usize));
    }

    #[test]
    fn nominal_declarations_intern_by_identity_not_layout() {
        let mut types = TypeArena::new();
        let first_struct = types.intern(TypeData::Struct(StructId(0)));
        let same_struct = types.intern(TypeData::Struct(StructId(0)));
        let other_struct = types.intern(TypeData::Struct(StructId(1)));
        let first_enum = types.intern(TypeData::Enum(EnumId(0)));
        let other_enum = types.intern(TypeData::Enum(EnumId(1)));
        assert_eq!(first_struct, same_struct);
        assert_ne!(first_struct, other_struct);
        assert_ne!(first_enum, other_enum);
        assert_ne!(first_struct, first_enum);
    }

    #[test]
    fn invalid_identity_fails_lookup_without_panicking() {
        let types = TypeArena::new();
        let invalid = TypeId(u32::MAX);
        assert!(!types.is_valid(invalid));
        assert_eq!(types.get(invalid), None);
        assert_eq!(types.format(invalid), "<invalid TypeId(4294967295)>");
    }
}
