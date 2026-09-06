//! Canonical semantic types and the minimal admitted target model.
#![allow(missing_docs)]

use std::collections::{BTreeSet, HashMap};
use std::fmt;
use std::sync::RwLock;

/// Session-local nominal identity of a source `struct` declaration.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StructId(pub u32);

/// Session-local nominal identity of a source `enum` declaration.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EnumId(pub u32);

/// Kind-safe declaration owner of a generic parameter. Function declarations
/// use their session-local numeric declaration index; nominal owners retain
/// their dedicated identity types.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GenericOwner {
    Function(u32),
    Struct(StructId),
    Enum(EnumId),
}

/// Semantic identity of a generic binder. Source spelling is metadata only.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct GenericParamId {
    pub owner: GenericOwner,
    pub index: u32,
}

/// Compiler-derived semantic capability available to generic constraints.
/// This is intentionally a closed set, not a user-implementable trait system.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Capability {
    Copy,
    Relocatable,
}

impl Capability {
    /// Central V15 implication lattice: `Copy` implies `Relocatable`.
    #[must_use]
    pub fn implies(self, required: Self) -> bool {
        self == required || matches!((self, required), (Self::Copy, Self::Relocatable))
    }
}

impl fmt::Display for Capability {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Copy => "Copy",
            Self::Relocatable => "Relocatable",
        })
    }
}

/// Canonical arena-owned type-argument-list identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TypeArgsId(pub u32);

/// Session-local identity of a concrete callable monomorphization.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct InstanceId(pub u32);

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
    /// One declaration-owned unconstrained type parameter.
    GenericParam(GenericParamId),
    /// Canonical application of a generic struct declaration.
    StructInstance(StructId, TypeArgsId),
    /// Canonical application of a generic enum declaration.
    EnumInstance(EnumId, TypeArgsId),
    /// Non-owning, non-null reference. `mutable` is write capability only and
    /// carries no uniqueness/noalias promise.
    Reference {
        pointee: TypeId,
        mutable: bool,
    },
    /// Fixed-length contiguous owning allocation. This is a compiler-known
    /// generic form rather than a nominal source declaration.
    Buffer {
        element: TypeId,
    },
    /// Fixed-size language-level collection. It intentionally remains a
    /// distinct semantic type from the lower-level `Buffer<T>` substrate.
    Array {
        element: TypeId,
    },
    /// Dynamic-length language-level collection with owned contiguous
    /// storage. Only the initialized prefix `[0, length)` contains values.
    List {
        element: TypeId,
    },
    /// Non-owning contiguous sequence plus length. `mutable` is write
    /// capability only and carries no uniqueness promise.
    View {
        element: TypeId,
        mutable: bool,
    },
}

/// Compiler-internal lifecycle properties. These are deliberately not a
/// source trait system.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(clippy::struct_excessive_bools)]
pub struct TypeProperties {
    /// False means the booleans below are conservative requirements for a
    /// symbolic/malformed type rather than a fabricated concrete answer.
    pub is_known: bool,
    pub is_copy: bool,
    /// Moving the value to different physical storage preserves its semantic
    /// value when the old location ceases to be live. This is not duplication.
    pub is_relocatable: bool,
    pub needs_drop: bool,
}

/// Result of the single semantic admission query used by owning collections.
/// Storage legality deliberately remains independent from public capabilities:
/// a borrowed descriptor can be `Relocatable` without being persistently
/// storable in an `Array` or `List`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CollectionElementAdmission {
    Admitted,
    InvalidType,
    MissingRelocatable,
    ForbiddenBorrow,
    SymbolicStorageUnknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct AggregateProperties {
    parameters: Vec<GenericParamId>,
    members: Vec<Vec<TypeId>>,
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
        if let Self::Struct(id) | Self::StructInstance(id, _) = self {
            Some(id)
        } else {
            None
        }
    }
    #[must_use]
    pub const fn as_enum(self) -> Option<EnumId> {
        if let Self::Enum(id) | Self::EnumInstance(id, _) = self {
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
            Self::GenericParam(id) => write!(f, "param({:?}:{})", id.owner, id.index),
            Self::StructInstance(id, args) => write!(f, "struct#{}<args#{}>", id.0, args.0),
            Self::EnumInstance(id, args) => write!(f, "enum#{}<args#{}>", id.0, args.0),
            Self::Reference { pointee, mutable } => {
                write!(f, "ref {}{pointee}", if *mutable { "mut " } else { "" })
            }
            Self::Buffer { element } => write!(f, "Buffer<{element}>"),
            Self::Array { element } => write!(f, "Array<{element}>"),
            Self::List { element } => write!(f, "List<{element}>"),
            Self::View { element, mutable } => write!(
                f,
                "{}<{element}>",
                if *mutable { "ViewMut" } else { "View" }
            ),
        }
    }
}

/// Session-owned bidirectional canonical type table.
///
/// The arena has ordinary Rust ownership, contains no global state and can be
/// cloned only when an unverified IR is deliberately cloned by tests/tools.
/// Production phase transitions move it forward with the program context.
#[derive(Debug)]
pub struct TypeArena {
    data: Vec<TypeData>,
    ids: HashMap<TypeData, TypeId>,
    argument_lists: Vec<Vec<TypeId>>,
    argument_ids: HashMap<Vec<TypeId>, TypeArgsId>,
    concrete_layouts: HashMap<TypeId, (u64, u64)>,
    struct_properties: HashMap<StructId, AggregateProperties>,
    enum_properties: HashMap<EnumId, AggregateProperties>,
    generic_capabilities: HashMap<GenericParamId, BTreeSet<Capability>>,
    generic_names: HashMap<GenericParamId, String>,
    property_cache: RwLock<HashMap<TypeId, TypeProperties>>,
}

impl Clone for TypeArena {
    fn clone(&self) -> Self {
        Self {
            data: self.data.clone(),
            ids: self.ids.clone(),
            argument_lists: self.argument_lists.clone(),
            argument_ids: self.argument_ids.clone(),
            concrete_layouts: self.concrete_layouts.clone(),
            struct_properties: self.struct_properties.clone(),
            enum_properties: self.enum_properties.clone(),
            generic_capabilities: self.generic_capabilities.clone(),
            generic_names: self.generic_names.clone(),
            property_cache: RwLock::new(
                self.property_cache
                    .read()
                    .expect("type-property cache lock")
                    .clone(),
            ),
        }
    }
}

impl PartialEq for TypeArena {
    fn eq(&self, other: &Self) -> bool {
        self.data == other.data
            && self.ids == other.ids
            && self.argument_lists == other.argument_lists
            && self.argument_ids == other.argument_ids
            && self.concrete_layouts == other.concrete_layouts
            && self.struct_properties == other.struct_properties
            && self.enum_properties == other.enum_properties
            && self.generic_capabilities == other.generic_capabilities
            && self.generic_names == other.generic_names
    }
}

impl Eq for TypeArena {}

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
            argument_lists: Vec::new(),
            argument_ids: HashMap::new(),
            concrete_layouts: HashMap::new(),
            struct_properties: HashMap::new(),
            enum_properties: HashMap::new(),
            generic_capabilities: HashMap::new(),
            generic_names: HashMap::new(),
            property_cache: RwLock::new(HashMap::new()),
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

    /// Interns a canonical argument list and generic nominal application.
    pub fn intern_struct_instance(
        &mut self,
        declaration: StructId,
        arguments: Vec<TypeId>,
    ) -> TypeId {
        let args = self.intern_arguments(arguments);
        self.intern(TypeData::StructInstance(declaration, args))
    }

    /// Interns a canonical argument list and generic nominal application.
    pub fn intern_enum_instance(&mut self, declaration: EnumId, arguments: Vec<TypeId>) -> TypeId {
        let args = self.intern_arguments(arguments);
        self.intern(TypeData::EnumInstance(declaration, args))
    }

    /// Interns a canonical non-owning reference type.
    pub fn intern_reference(&mut self, pointee: TypeId, mutable: bool) -> TypeId {
        self.intern(TypeData::Reference { pointee, mutable })
    }

    pub fn intern_buffer(&mut self, element: TypeId) -> TypeId {
        self.intern(TypeData::Buffer { element })
    }

    pub fn intern_array(&mut self, element: TypeId) -> TypeId {
        self.intern(TypeData::Array { element })
    }

    pub fn intern_list(&mut self, element: TypeId) -> TypeId {
        self.intern(TypeData::List { element })
    }

    pub fn intern_view(&mut self, element: TypeId, mutable: bool) -> TypeId {
        self.intern(TypeData::View { element, mutable })
    }

    /// Registers declaration-owned member types for structural lifecycle
    /// queries. Later phases can consequently use one TypeId-based API.
    pub fn register_struct_properties(
        &mut self,
        id: StructId,
        parameters: Vec<GenericParamId>,
        fields: Vec<TypeId>,
    ) {
        self.struct_properties.insert(
            id,
            AggregateProperties {
                parameters,
                members: vec![fields],
            },
        );
        self.property_cache
            .write()
            .expect("type-property cache lock")
            .clear();
    }

    pub fn register_enum_properties(
        &mut self,
        id: EnumId,
        parameters: Vec<GenericParamId>,
        variants: Vec<Vec<TypeId>>,
    ) {
        self.enum_properties.insert(
            id,
            AggregateProperties {
                parameters,
                members: variants,
            },
        );
        self.property_cache
            .write()
            .expect("type-property cache lock")
            .clear();
    }

    /// Registers declaration-owned guarantees separately from concrete type
    /// properties. The generic parameter's canonical `TypeId` remains unchanged.
    pub fn register_generic_capabilities(
        &mut self,
        id: GenericParamId,
        source_name: String,
        capabilities: impl IntoIterator<Item = Capability>,
    ) {
        self.generic_capabilities
            .insert(id, capabilities.into_iter().collect());
        self.generic_names.insert(id, source_name);
    }

    #[must_use]
    pub fn generic_capabilities(&self, id: GenericParamId) -> Option<&BTreeSet<Capability>> {
        self.generic_capabilities.get(&id)
    }

    #[must_use]
    pub fn generic_name(&self, id: GenericParamId) -> Option<&str> {
        self.generic_names.get(&id).map(String::as_str)
    }

    fn intern_arguments(&mut self, arguments: Vec<TypeId>) -> TypeArgsId {
        if let Some(id) = self.argument_ids.get(&arguments) {
            return *id;
        }
        let id = TypeArgsId(
            u32::try_from(self.argument_lists.len()).expect("type argument arena fits u32"),
        );
        self.argument_lists.push(arguments.clone());
        self.argument_ids.insert(arguments, id);
        id
    }

    #[must_use]
    pub fn arguments(&self, id: TypeArgsId) -> Option<&[TypeId]> {
        self.argument_lists.get(id.0 as usize).map(Vec::as_slice)
    }

    #[must_use]
    pub fn type_arguments(&self, ty: TypeId) -> Option<&[TypeId]> {
        match self.get(ty) {
            Some(TypeData::StructInstance(_, args) | TypeData::EnumInstance(_, args)) => {
                self.arguments(*args)
            }
            _ => None,
        }
    }

    #[must_use]
    pub fn generic_param(&self, ty: TypeId) -> Option<GenericParamId> {
        match self.get(ty) {
            Some(TypeData::GenericParam(id)) => Some(*id),
            _ => None,
        }
    }

    #[must_use]
    pub fn contains_generic(&self, ty: TypeId) -> bool {
        match self.get(ty) {
            Some(TypeData::GenericParam(_)) => true,
            Some(TypeData::StructInstance(_, args) | TypeData::EnumInstance(_, args)) => {
                self.arguments(*args).is_some_and(|arguments| {
                    arguments
                        .iter()
                        .any(|argument| self.contains_generic(*argument))
                })
            }
            Some(TypeData::Reference { pointee, .. }) => self.contains_generic(*pointee),
            Some(
                TypeData::Buffer { element }
                | TypeData::Array { element }
                | TypeData::List { element }
                | TypeData::View { element, .. },
            ) => self.contains_generic(*element),
            _ => false,
        }
    }

    pub fn cache_layout(&mut self, ty: TypeId, size: u64, align: u64) {
        self.concrete_layouts.insert(ty, (size, align));
    }

    #[must_use]
    pub fn cached_layout(&self, ty: TypeId) -> Option<(u64, u64)> {
        self.concrete_layouts.get(&ty).copied()
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
            Some(TypeData::Struct(value) | TypeData::StructInstance(value, _)) => Some(*value),
            _ => None,
        }
    }

    #[must_use]
    pub fn enum_id(&self, id: TypeId) -> Option<EnumId> {
        match self.get(id) {
            Some(TypeData::Enum(value) | TypeData::EnumInstance(value, _)) => Some(*value),
            _ => None,
        }
    }

    /// Returns pointee and write capability for a semantic reference type.
    #[must_use]
    pub fn reference_info(&self, id: TypeId) -> Option<(TypeId, bool)> {
        match self.get(id) {
            Some(TypeData::Reference { pointee, mutable }) => Some((*pointee, *mutable)),
            _ => None,
        }
    }

    #[must_use]
    pub fn buffer_element(&self, id: TypeId) -> Option<TypeId> {
        match self.get(id) {
            Some(TypeData::Buffer { element }) => Some(*element),
            _ => None,
        }
    }

    #[must_use]
    pub fn array_element(&self, id: TypeId) -> Option<TypeId> {
        match self.get(id) {
            Some(TypeData::Array { element }) => Some(*element),
            _ => None,
        }
    }

    #[must_use]
    pub fn list_element(&self, id: TypeId) -> Option<TypeId> {
        match self.get(id) {
            Some(TypeData::List { element }) => Some(*element),
            _ => None,
        }
    }

    /// Element type for any owning contiguous descriptor.
    #[must_use]
    pub fn owning_contiguous_element(&self, id: TypeId) -> Option<TypeId> {
        self.buffer_element(id)
            .or_else(|| self.array_element(id))
            .or_else(|| self.list_element(id))
    }

    #[must_use]
    pub fn view_info(&self, id: TypeId) -> Option<(TypeId, bool)> {
        match self.get(id) {
            Some(TypeData::View { element, mutable }) => Some((*element, *mutable)),
            _ => None,
        }
    }

    /// Central lifecycle classification for a canonical semantic type.
    /// Aggregate properties are derived transitively after substituting their
    /// declaration binders. Unresolved parameters are conservatively treated
    /// as non-Copy and potentially needing drop, so a parametric body cannot
    /// duplicate or leak an unknown owner.
    #[must_use]
    pub fn properties(&self, id: TypeId) -> Option<TypeProperties> {
        self.get(id)?;
        if !self.contains_generic(id) {
            let cached = self
                .property_cache
                .read()
                .expect("type-property cache lock")
                .get(&id)
                .copied();
            if let Some(properties) = cached {
                return Some(properties);
            }
        }
        let properties =
            self.properties_with_substitution(id, &HashMap::new(), &mut BTreeSet::new());
        if !self.contains_generic(id) {
            self.property_cache
                .write()
                .expect("type-property cache lock")
                .insert(id, properties);
        }
        Some(properties)
    }

    fn properties_with_substitution(
        &self,
        id: TypeId,
        substitution: &HashMap<GenericParamId, TypeId>,
        visiting: &mut BTreeSet<TypeId>,
    ) -> TypeProperties {
        let unknown = TypeProperties {
            is_known: false,
            is_copy: false,
            is_relocatable: false,
            needs_drop: true,
        };
        let Some(data) = self.get(id).copied() else {
            return unknown;
        };
        let aggregate_ty = id;
        match data {
            TypeData::Bool
            | TypeData::Integer(_)
            | TypeData::Float(_)
            | TypeData::Reference { .. }
            | TypeData::View { .. } => TypeProperties {
                is_known: true,
                is_copy: true,
                is_relocatable: true,
                needs_drop: false,
            },
            TypeData::Buffer { .. } | TypeData::Array { .. } | TypeData::List { .. } => {
                TypeProperties {
                    is_known: true,
                    is_copy: false,
                    is_relocatable: true,
                    needs_drop: true,
                }
            }
            TypeData::GenericParam(parameter) => {
                substitution.get(&parameter).map_or(unknown, |ty| {
                    if *ty == id {
                        unknown
                    } else {
                        self.properties_with_substitution(*ty, substitution, visiting)
                    }
                })
            }
            TypeData::Struct(id) => {
                self.aggregate_properties(false, id.0, aggregate_ty, None, substitution, visiting)
            }
            TypeData::Enum(id) => {
                self.aggregate_properties(true, id.0, aggregate_ty, None, substitution, visiting)
            }
            TypeData::StructInstance(id, args) => self.aggregate_properties(
                false,
                id.0,
                aggregate_ty,
                Some(args),
                substitution,
                visiting,
            ),
            TypeData::EnumInstance(id, args) => self.aggregate_properties(
                true,
                id.0,
                aggregate_ty,
                Some(args),
                substitution,
                visiting,
            ),
        }
    }

    fn aggregate_properties(
        &self,
        is_enum: bool,
        raw_id: u32,
        aggregate_ty: TypeId,
        arguments: Option<TypeArgsId>,
        outer: &HashMap<GenericParamId, TypeId>,
        visiting: &mut BTreeSet<TypeId>,
    ) -> TypeProperties {
        if !visiting.insert(aggregate_ty) {
            return TypeProperties {
                is_known: false,
                is_copy: false,
                is_relocatable: false,
                needs_drop: true,
            };
        }
        let definition = if is_enum {
            self.enum_properties.get(&EnumId(raw_id))
        } else {
            self.struct_properties.get(&StructId(raw_id))
        };
        let Some(definition) = definition else {
            visiting.remove(&aggregate_ty);
            return TypeProperties {
                is_known: false,
                is_copy: false,
                is_relocatable: false,
                needs_drop: true,
            };
        };
        let mut substitution = outer.clone();
        if let Some(arguments) = arguments {
            let Some(arguments) = self.arguments(arguments) else {
                visiting.remove(&aggregate_ty);
                return TypeProperties {
                    is_known: false,
                    is_copy: false,
                    is_relocatable: false,
                    needs_drop: true,
                };
            };
            for (parameter, argument) in definition.parameters.iter().zip(arguments) {
                substitution.insert(*parameter, *argument);
            }
        } else if !definition.parameters.is_empty() {
            visiting.remove(&aggregate_ty);
            return TypeProperties {
                is_known: false,
                is_copy: false,
                is_relocatable: false,
                needs_drop: true,
            };
        }
        let mut result = TypeProperties {
            is_known: true,
            is_copy: true,
            is_relocatable: true,
            needs_drop: false,
        };
        for member in definition.members.iter().flatten() {
            let properties = self.properties_with_substitution(*member, &substitution, visiting);
            result.is_known &= properties.is_known;
            result.is_copy &= properties.is_copy;
            result.is_relocatable &= properties.is_relocatable;
            result.needs_drop |= properties.needs_drop;
        }
        visiting.remove(&aggregate_ty);
        result
    }

    #[must_use]
    pub fn is_copy(&self, id: TypeId) -> bool {
        self.properties(id)
            .is_some_and(|properties| properties.is_copy)
    }

    /// Concrete relocation property. Symbolic code should use
    /// [`Self::guarantees_capability`] instead.
    #[must_use]
    pub fn is_relocatable(&self, id: TypeId) -> bool {
        self.properties(id)
            .is_some_and(|properties| properties.is_relocatable)
    }

    /// Answers whether a concrete or symbolic type is guaranteed to provide
    /// a capability in its current declaration context.
    #[must_use]
    pub fn guarantees_capability(&self, id: TypeId, capability: Capability) -> bool {
        self.guarantees_capability_with_substitution(
            id,
            capability,
            &HashMap::new(),
            &mut BTreeSet::new(),
        )
    }

    #[must_use]
    pub fn guarantees_copy(&self, id: TypeId) -> bool {
        self.guarantees_capability(id, Capability::Copy)
    }

    #[must_use]
    pub fn guarantees_relocatable(&self, id: TypeId) -> bool {
        self.guarantees_capability(id, Capability::Relocatable)
    }

    fn guarantees_capability_with_substitution(
        &self,
        id: TypeId,
        capability: Capability,
        substitution: &HashMap<GenericParamId, TypeId>,
        visiting: &mut BTreeSet<(Capability, TypeId)>,
    ) -> bool {
        if !visiting.insert((capability, id)) {
            return false;
        }
        let result = match self.get(id).copied() {
            Some(TypeData::GenericParam(parameter)) => substitution.get(&parameter).map_or_else(
                || {
                    self.generic_capabilities(parameter)
                        .is_some_and(|provided| {
                            provided.iter().any(|value| value.implies(capability))
                        })
                },
                |ty| {
                    *ty != id
                        && self.guarantees_capability_with_substitution(
                            *ty,
                            capability,
                            substitution,
                            visiting,
                        )
                },
            ),
            Some(TypeData::Struct(declaration)) => self.aggregate_guarantees_capability(
                false,
                declaration.0,
                None,
                capability,
                substitution,
                visiting,
            ),
            Some(TypeData::Enum(declaration)) => self.aggregate_guarantees_capability(
                true,
                declaration.0,
                None,
                capability,
                substitution,
                visiting,
            ),
            Some(TypeData::StructInstance(declaration, arguments)) => self
                .aggregate_guarantees_capability(
                    false,
                    declaration.0,
                    Some(arguments),
                    capability,
                    substitution,
                    visiting,
                ),
            Some(TypeData::EnumInstance(declaration, arguments)) => self
                .aggregate_guarantees_capability(
                    true,
                    declaration.0,
                    Some(arguments),
                    capability,
                    substitution,
                    visiting,
                ),
            Some(
                TypeData::Bool
                | TypeData::Integer(_)
                | TypeData::Float(_)
                | TypeData::Reference { .. }
                | TypeData::View { .. },
            ) => true,
            Some(TypeData::Buffer { .. } | TypeData::Array { .. } | TypeData::List { .. }) => {
                capability == Capability::Relocatable
            }
            None => false,
        };
        visiting.remove(&(capability, id));
        result
    }

    fn aggregate_guarantees_capability(
        &self,
        is_enum: bool,
        raw_id: u32,
        arguments: Option<TypeArgsId>,
        capability: Capability,
        outer: &HashMap<GenericParamId, TypeId>,
        visiting: &mut BTreeSet<(Capability, TypeId)>,
    ) -> bool {
        let definition = if is_enum {
            self.enum_properties.get(&EnumId(raw_id))
        } else {
            self.struct_properties.get(&StructId(raw_id))
        };
        let Some(definition) = definition else {
            return false;
        };
        let mut substitution = outer.clone();
        match arguments {
            Some(arguments) => {
                let Some(arguments) = self.arguments(arguments) else {
                    return false;
                };
                if arguments.len() != definition.parameters.len() {
                    return false;
                }
                for (parameter, argument) in definition.parameters.iter().zip(arguments) {
                    substitution.insert(*parameter, *argument);
                }
            }
            None if !definition.parameters.is_empty() => return false,
            None => {}
        }
        definition.members.iter().flatten().all(|member| {
            self.guarantees_capability_with_substitution(
                *member,
                capability,
                &substitution,
                visiting,
            )
        })
    }

    #[must_use]
    pub fn needs_drop(&self, id: TypeId) -> bool {
        self.properties(id)
            .is_some_and(|properties| properties.needs_drop)
    }

    /// Whether a concrete element type satisfies the deliberately restricted
    /// Vertical-10 Buffer/View capability contract.
    #[must_use]
    pub fn is_admitted_buffer_element(&self, id: TypeId) -> bool {
        self.is_valid(id)
            && !self.contains_generic(id)
            && self.is_copy(id)
            && !self.needs_drop(id)
            && !self.contains_reference(id)
            && !self.contains_view(id)
            && !self.contains_owning(id)
    }

    /// Central Vertical-16 admission proof for owning collection elements.
    ///
    /// Concrete values are admitted exactly when relocation glue is available
    /// and current lifetime rules prove that no reference or view is stored.
    /// A symbolic capability alone cannot prove the latter because references
    /// themselves are Relocatable, so unresolved element types remain
    /// conservatively rejected without adding a public negative capability.
    #[must_use]
    pub fn collection_element_admission(&self, id: TypeId) -> CollectionElementAdmission {
        if !self.is_valid(id) {
            return CollectionElementAdmission::InvalidType;
        }
        if self.contains_generic(id) {
            return if self.guarantees_relocatable(id) {
                CollectionElementAdmission::SymbolicStorageUnknown
            } else {
                CollectionElementAdmission::MissingRelocatable
            };
        }
        if self.contains_reference(id) || self.contains_view(id) {
            return CollectionElementAdmission::ForbiddenBorrow;
        }
        if !self.is_relocatable(id) {
            return CollectionElementAdmission::MissingRelocatable;
        }
        CollectionElementAdmission::Admitted
    }

    /// Array and List deliberately share one V16 storage predicate.
    #[must_use]
    pub fn is_admitted_array_element(&self, id: TypeId) -> bool {
        self.collection_element_admission(id) == CollectionElementAdmission::Admitted
    }

    #[must_use]
    pub fn is_admitted_list_element(&self, id: TypeId) -> bool {
        self.collection_element_admission(id) == CollectionElementAdmission::Admitted
    }

    #[must_use]
    pub fn contains_owning(&self, id: TypeId) -> bool {
        self.contains_capability(id, 2, &HashMap::new(), &mut BTreeSet::new())
    }

    #[must_use]
    pub fn contains_view(&self, id: TypeId) -> bool {
        self.contains_capability(id, 1, &HashMap::new(), &mut BTreeSet::new())
    }

    /// Whether this type is, or recursively contains as a generic argument, a
    /// V9 reference that cannot be persisted in a V10 aggregate.
    #[must_use]
    pub fn contains_reference(&self, id: TypeId) -> bool {
        self.contains_capability(id, 0, &HashMap::new(), &mut BTreeSet::new())
    }

    fn contains_capability(
        &self,
        id: TypeId,
        capability: u8,
        substitution: &HashMap<GenericParamId, TypeId>,
        visiting: &mut BTreeSet<(u8, TypeId)>,
    ) -> bool {
        let aggregate_ty = id;
        match self.get(id).copied() {
            Some(TypeData::Reference { pointee, .. }) => {
                capability == 0
                    || self.contains_capability(pointee, capability, substitution, visiting)
            }
            Some(TypeData::View { element, .. }) => {
                capability == 1
                    || self.contains_capability(element, capability, substitution, visiting)
            }
            Some(
                TypeData::Buffer { element }
                | TypeData::Array { element }
                | TypeData::List { element },
            ) => {
                capability == 2
                    || self.contains_capability(element, capability, substitution, visiting)
            }
            Some(TypeData::GenericParam(parameter)) => {
                substitution.get(&parameter).is_some_and(|ty| {
                    *ty != id && self.contains_capability(*ty, capability, substitution, visiting)
                })
            }
            Some(TypeData::Struct(id)) => self.aggregate_contains_capability(
                false,
                id.0,
                aggregate_ty,
                None,
                capability,
                substitution,
                visiting,
            ),
            Some(TypeData::Enum(id)) => self.aggregate_contains_capability(
                true,
                id.0,
                aggregate_ty,
                None,
                capability,
                substitution,
                visiting,
            ),
            Some(TypeData::StructInstance(id, args)) => self.aggregate_contains_capability(
                false,
                id.0,
                aggregate_ty,
                Some(args),
                capability,
                substitution,
                visiting,
            ),
            Some(TypeData::EnumInstance(id, args)) => self.aggregate_contains_capability(
                true,
                id.0,
                aggregate_ty,
                Some(args),
                capability,
                substitution,
                visiting,
            ),
            Some(TypeData::Bool | TypeData::Integer(_) | TypeData::Float(_)) | None => false,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn aggregate_contains_capability(
        &self,
        is_enum: bool,
        raw_id: u32,
        aggregate_ty: TypeId,
        arguments: Option<TypeArgsId>,
        capability: u8,
        outer: &HashMap<GenericParamId, TypeId>,
        visiting: &mut BTreeSet<(u8, TypeId)>,
    ) -> bool {
        let key = (capability, aggregate_ty);
        if !visiting.insert(key) {
            return false;
        }
        let definition = if is_enum {
            self.enum_properties.get(&EnumId(raw_id))
        } else {
            self.struct_properties.get(&StructId(raw_id))
        };
        let Some(definition) = definition else {
            visiting.remove(&key);
            return false;
        };
        let mut substitution = outer.clone();
        if let Some(arguments) = arguments
            && let Some(arguments) = self.arguments(arguments)
        {
            for (parameter, argument) in definition.parameters.iter().zip(arguments) {
                substitution.insert(*parameter, *argument);
            }
        }
        let result =
            definition.members.iter().flatten().any(|member| {
                self.contains_capability(*member, capability, &substitution, visiting)
            });
        visiting.remove(&key);
        result
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

    /// Applies one explicit substitution recursively and interns every newly
    /// formed nominal application in this arena.
    pub fn substitute(
        &mut self,
        ty: TypeId,
        substitution: &Substitution,
    ) -> Result<TypeId, GenericParamId> {
        match self.get(ty).copied() {
            Some(TypeData::GenericParam(param)) => substitution.get(param).ok_or(param),
            Some(TypeData::StructInstance(id, args)) => {
                let source = self
                    .arguments(args)
                    .expect("valid argument identity")
                    .to_vec();
                let arguments = source
                    .into_iter()
                    .map(|argument| self.substitute(argument, substitution))
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(self.intern_struct_instance(id, arguments))
            }
            Some(TypeData::EnumInstance(id, args)) => {
                let source = self
                    .arguments(args)
                    .expect("valid argument identity")
                    .to_vec();
                let arguments = source
                    .into_iter()
                    .map(|argument| self.substitute(argument, substitution))
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(self.intern_enum_instance(id, arguments))
            }
            Some(TypeData::Reference { pointee, mutable }) => {
                let pointee = self.substitute(pointee, substitution)?;
                Ok(self.intern_reference(pointee, mutable))
            }
            Some(TypeData::Buffer { element }) => {
                let element = self.substitute(element, substitution)?;
                Ok(self.intern_buffer(element))
            }
            Some(TypeData::Array { element }) => {
                let element = self.substitute(element, substitution)?;
                Ok(self.intern_array(element))
            }
            Some(TypeData::List { element }) => {
                let element = self.substitute(element, substitution)?;
                Ok(self.intern_list(element))
            }
            Some(TypeData::View { element, mutable }) => {
                let element = self.substitute(element, substitution)?;
                Ok(self.intern_view(element, mutable))
            }
            Some(_) | None => Ok(ty),
        }
    }

    /// Read-only substitution used by verifiers after monomorphization. Every
    /// result must already have been interned by the instantiator.
    pub fn substituted_existing(
        &self,
        ty: TypeId,
        substitution: &Substitution,
    ) -> Result<TypeId, GenericParamId> {
        match self.get(ty).copied() {
            Some(TypeData::GenericParam(param)) => substitution.get(param).ok_or(param),
            Some(TypeData::StructInstance(id, args)) => {
                let arguments = self
                    .arguments(args)
                    .expect("valid argument identity")
                    .iter()
                    .map(|argument| self.substituted_existing(*argument, substitution))
                    .collect::<Result<Vec<_>, _>>()?;
                let args = self
                    .argument_ids
                    .get(&arguments)
                    .copied()
                    .expect("monomorphizer interned substituted arguments");
                Ok(*self
                    .ids
                    .get(&TypeData::StructInstance(id, args))
                    .expect("monomorphizer interned substituted struct"))
            }
            Some(TypeData::EnumInstance(id, args)) => {
                let arguments = self
                    .arguments(args)
                    .expect("valid argument identity")
                    .iter()
                    .map(|argument| self.substituted_existing(*argument, substitution))
                    .collect::<Result<Vec<_>, _>>()?;
                let args = self
                    .argument_ids
                    .get(&arguments)
                    .copied()
                    .expect("monomorphizer interned substituted arguments");
                Ok(*self
                    .ids
                    .get(&TypeData::EnumInstance(id, args))
                    .expect("monomorphizer interned substituted enum"))
            }
            Some(TypeData::Reference { pointee, mutable }) => {
                let pointee = self.substituted_existing(pointee, substitution)?;
                Ok(*self
                    .ids
                    .get(&TypeData::Reference { pointee, mutable })
                    .expect("monomorphizer interned substituted reference"))
            }
            Some(TypeData::Buffer { element }) => {
                let element = self.substituted_existing(element, substitution)?;
                Ok(*self
                    .ids
                    .get(&TypeData::Buffer { element })
                    .expect("monomorphizer interned substituted Buffer"))
            }
            Some(TypeData::Array { element }) => {
                let element = self.substituted_existing(element, substitution)?;
                Ok(*self
                    .ids
                    .get(&TypeData::Array { element })
                    .expect("monomorphizer interned substituted Array"))
            }
            Some(TypeData::List { element }) => {
                let element = self.substituted_existing(element, substitution)?;
                Ok(*self
                    .ids
                    .get(&TypeData::List { element })
                    .expect("monomorphizer interned substituted List"))
            }
            Some(TypeData::View { element, mutable }) => {
                let element = self.substituted_existing(element, substitution)?;
                Ok(*self
                    .ids
                    .get(&TypeData::View { element, mutable })
                    .expect("monomorphizer interned substituted View"))
            }
            Some(_) | None => Ok(ty),
        }
    }
}

/// Reusable declaration-parameter to canonical-type mapping.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Substitution {
    entries: HashMap<GenericParamId, TypeId>,
}

impl Substitution {
    #[must_use]
    pub fn new(
        parameters: impl IntoIterator<Item = GenericParamId>,
        arguments: impl IntoIterator<Item = TypeId>,
    ) -> Self {
        Self {
            entries: parameters.into_iter().zip(arguments).collect(),
        }
    }

    #[must_use]
    pub fn get(&self, parameter: GenericParamId) -> Option<TypeId> {
        self.entries.get(&parameter).copied()
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

    #[test]
    fn generic_parameters_applications_and_substitution_are_canonical() {
        let mut types = TypeArena::new();
        let parameter = GenericParamId {
            owner: GenericOwner::Struct(StructId(0)),
            index: 0,
        };
        let other_owner = GenericParamId {
            owner: GenericOwner::Function(0),
            index: 0,
        };
        let parameter_ty = types.intern(TypeData::GenericParam(parameter));
        let other_parameter_ty = types.intern(TypeData::GenericParam(other_owner));
        assert_ne!(parameter_ty, other_parameter_ty);

        let pair = types.intern_struct_instance(StructId(0), vec![TypeId::INT64, TypeId::FLOAT64]);
        let repeated =
            types.intern_struct_instance(StructId(0), vec![TypeId::INT64, TypeId::FLOAT64]);
        let reversed =
            types.intern_struct_instance(StructId(0), vec![TypeId::FLOAT64, TypeId::INT64]);
        let other_nominal =
            types.intern_struct_instance(StructId(1), vec![TypeId::INT64, TypeId::FLOAT64]);
        assert_eq!(pair, repeated);
        assert_ne!(pair, reversed);
        assert_ne!(pair, other_nominal);

        let symbolic =
            types.intern_struct_instance(StructId(0), vec![parameter_ty, TypeId::FLOAT64]);
        let substitution = Substitution::new([parameter], [TypeId::INT64]);
        assert_eq!(types.substitute(symbolic, &substitution), Ok(pair));
    }
}
