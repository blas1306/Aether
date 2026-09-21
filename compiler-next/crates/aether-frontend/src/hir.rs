//! Alias-canonicalized, nominal and fully typed HIR.
#![allow(missing_docs)]
#![allow(
    clippy::cast_possible_truncation,
    clippy::cast_possible_wrap,
    clippy::cast_precision_loss,
    clippy::enum_glob_use,
    clippy::many_single_char_names,
    clippy::float_cmp,
    clippy::semicolon_if_nothing_returned,
    clippy::too_many_arguments,
    clippy::too_many_lines,
    clippy::unused_self
)]
mod classes;
mod mathematical;
use crate::{ClassId, ClassOp, ClassTokenKind};
use mathematical::{
    concrete_behavior_op, math_element_op, matrix_matrix_recipe, matrix_vector_recipe,
    vector_product_recipe, verify_math_element_op, zero_value,
};

use crate::AlgebraicCapability;
use crate::{
    AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstMatchArm, AstMatchMode,
    AstStmtKind, AstType, AstUnaryOp, BehavioralCapability, Capability, CollectionElementAdmission,
    CollectionKind, Diagnostic, DiagnosticCategory, EnumId, FieldId, FloatType, GenericOwner,
    GenericParamId, IntegerType, ParsedAst, Phase, SourceId, Span, StructId, Substitution,
    TargetProperties, TypeArena, TypeData, TypeId, VariantId,
};
use crate::{IndexSemantics, Orientation};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ModuleId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct PackageId(pub u32);
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OriginKey {
    Project,
    Toolchain,
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct PackagePath(pub Vec<String>);
impl PackagePath {
    #[must_use]
    pub fn is_valid(&self) -> bool {
        !self.0.is_empty()
    }
    #[must_use]
    pub fn source(&self) -> String {
        self.0.join(".")
    }
    #[must_use]
    pub fn canonical(&self) -> String {
        self.0.join("::")
    }
    #[must_use]
    pub fn starts_with(&self, other: &Self) -> bool {
        self.0.starts_with(&other.0)
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PackageKey {
    Named {
        origin: OriginKey,
        path: PackagePath,
    },
    Anonymous,
}
impl PackageKey {
    #[must_use]
    pub fn named(origin: OriginKey, path: PackagePath) -> Self {
        Self::Named { origin, path }
    }

    #[must_use]
    pub const fn named_parts(&self) -> Option<(&OriginKey, &PackagePath)> {
        match self {
            Self::Named { origin, path } => Some((origin, path)),
            Self::Anonymous => None,
        }
    }

    #[must_use]
    pub fn display(&self) -> String {
        match self {
            Self::Named { path, .. } => path.source(),
            Self::Anonymous => "<anonymous package>".into(),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LogicalSourceKey(pub String);
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SourceUnitKey {
    pub package: PackageKey,
    pub logical_source: LogicalSourceKey,
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SymbolKey {
    pub package: PackageKey,
    pub member: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedImport {
    pub name: String,
    pub module: ModuleId,
    pub package: PackageId,
    pub target: PackageKey,
    pub alias: Option<String>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleInfo {
    pub id: ModuleId,
    pub key: SourceUnitKey,
    pub package: PackageId,
    /// Human-readable label only; nominal identity is always `key.package`.
    pub display_name: String,
    pub source: SourceId,
    pub source_name: String,
    pub imports: Vec<ResolvedImport>,
    pub semantic_dependencies: BTreeSet<ModuleId>,
}
#[derive(Clone, Debug)]
pub struct ParsedModule {
    pub info: ModuleInfo,
    pub ast: ParsedAst,
}
#[derive(Clone, Debug)]
pub struct ParsedProgram {
    pub modules: Vec<ParsedModule>,
    pub entry: ModuleId,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FunctionId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LocalId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CatchId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FinallyId(pub u32);
/// Function-local source loop identity, assigned in lexical discovery order.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct LoopId(pub u32);
/// Function-local call identity, assigned in source evaluation order.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CallSiteId(pub u32);
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParameterSignature {
    pub name: String,
    pub ty: TypeId,
    pub mutability: crate::BindingMutability,
    pub default: Option<DefaultArgumentTemplate>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DefaultArgumentTemplate {
    pub parameter_index: u32,
    pub expression: AstExpr,
    pub equals_span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FunctionSignature {
    pub id: FunctionId,
    pub module: ModuleId,
    pub name: String,
    pub generic_parameters: Vec<GenericParamInfo>,
    pub parameters: Vec<ParameterSignature>,
    pub return_type: TypeId,
    pub span: Span,
}

impl FunctionSignature {
    #[must_use]
    pub fn minimum_arity(&self) -> usize {
        self.parameters
            .iter()
            .position(|parameter| parameter.default.is_some())
            .unwrap_or(self.parameters.len())
    }
}
impl FunctionSignature {
    /// Stable logical identity, independent of the importing spelling and dense session IDs.
    #[must_use]
    pub fn symbol_key(&self, modules: &[ModuleInfo]) -> SymbolKey {
        SymbolKey {
            package: modules[self.module.0 as usize].key.package.clone(),
            member: self.name.clone(),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GenericParamInfo {
    pub id: GenericParamId,
    pub name: String,
    pub ty: TypeId,
    pub capabilities: BTreeSet<Capability>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypeAliasInfo {
    pub module: ModuleId,
    pub name: String,
    pub target_spelling: String,
    pub canonical: TypeId,
    pub span: Span,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TypeLayout {
    pub size: u64,
    pub align: u64,
}

/// Central physical choice for a nullable semantic type.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NullableLayout {
    Niche {
        layout: TypeLayout,
    },
    Tagged {
        layout: TypeLayout,
        tag_offset: u64,
        payload_offset: u64,
        payload: TypeLayout,
    },
}

#[must_use]
pub fn nullable_layout_of(
    types: &TypeArena,
    nullable: TypeId,
    target: TargetProperties,
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> Option<NullableLayout> {
    let payload_ty = types.nullable_payload(nullable)?;
    let payload = layout_of(types, payload_ty, target, structs, enums)?;
    if matches!(
        types.get(payload_ty),
        Some(
            TypeData::String
                | TypeData::Class(_)
                | TypeData::Reference { .. }
                | TypeData::Function { .. }
        )
    ) {
        return Some(NullableLayout::Niche { layout: payload });
    }
    let payload_offset = 1_u64.div_ceil(payload.align) * payload.align;
    let size = (payload_offset + payload.size).div_ceil(payload.align) * payload.align;
    Some(NullableLayout::Tagged {
        layout: TypeLayout {
            size,
            align: payload.align,
        },
        tag_offset: 0,
        payload_offset,
        payload,
    })
}

/// Returns the session's target-specific layout for a canonical type.
///
/// Aggregate entries are the caches populated once during semantic analysis;
/// scalar and target-sized integer layouts are computed from `target`. A
/// compilation session has exactly one target, so no cross-target cache key or
/// persistent layout identity is needed in Vertical-10.
#[must_use]
pub fn layout_of(
    types: &TypeArena,
    ty: TypeId,
    target: TargetProperties,
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> Option<TypeLayout> {
    Some(match types.get(ty)? {
        TypeData::Bool => TypeLayout { size: 1, align: 1 },
        TypeData::Char | TypeData::Float(FloatType::Float32) => TypeLayout { size: 4, align: 4 },
        TypeData::Integer(integer) => {
            let bytes = u64::from(integer.bits(target) / 8);
            TypeLayout {
                size: bytes,
                align: bytes,
            }
        }
        TypeData::Float(FloatType::Float64) => TypeLayout { size: 8, align: 8 },
        TypeData::Struct(id) => {
            let info = structs.get(id.0 as usize)?;
            if !info.generic_parameters.is_empty() {
                return None;
            }
            info.layout
        }
        TypeData::Enum(id) => {
            let info = enums.get(id.0 as usize)?;
            if !info.generic_parameters.is_empty() {
                return None;
            }
            info.layout
        }
        TypeData::StructInstance(_, _) | TypeData::EnumInstance(_, _) => {
            let (size, align) = types.cached_layout(ty)?;
            TypeLayout { size, align }
        }
        TypeData::Interface(_) | TypeData::InterfaceKeepalive { .. } => {
            let size = u64::from(target.pointer_width / 8);
            TypeLayout {
                size: size * 2,
                align: size,
            }
        }
        TypeData::String
        | TypeData::Class(_)
        | TypeData::ClassToken { .. }
        | TypeData::Reference { .. }
        | TypeData::Function { .. } => TypeLayout {
            size: u64::from(target.pointer_width / 8),
            align: u64::from(target.pointer_width / 8),
        },
        TypeData::Nullable(_) => match nullable_layout_of(types, ty, target, structs, enums)? {
            NullableLayout::Niche { layout } | NullableLayout::Tagged { layout, .. } => layout,
        },
        TypeData::Buffer { .. }
        | TypeData::Vector { .. }
        | TypeData::Array { .. }
        | TypeData::View { .. } => TypeLayout {
            size: u64::from(target.pointer_width / 4),
            align: u64::from(target.pointer_width / 8),
        },
        TypeData::MatrixView { .. } => TypeLayout {
            size: 5 * u64::from(target.pointer_width / 8),
            align: u64::from(target.pointer_width / 8),
        },
        TypeData::VectorView { .. } | TypeData::Matrix { .. } | TypeData::List { .. } => {
            TypeLayout {
                size: 3 * u64::from(target.pointer_width / 8),
                align: u64::from(target.pointer_width / 8),
            }
        }
        TypeData::Void | TypeData::GenericParam(_) => return None,
    })
}

/// Formats a canonical type for source diagnostics and IR inspection without
/// exposing a raw arena index as the only description.
#[must_use]
pub fn format_type(
    types: &TypeArena,
    ty: TypeId,
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> String {
    match types.get(ty) {
        Some(TypeData::Struct(id)) => structs
            .get(id.0 as usize)
            .map_or_else(|| format!("struct#{}", id.0), |info| info.name.clone()),
        Some(TypeData::Enum(id)) => enums
            .get(id.0 as usize)
            .map_or_else(|| format!("enum#{}", id.0), |info| info.name.clone()),
        Some(TypeData::StructInstance(id, args)) => {
            let name = structs
                .get(id.0 as usize)
                .map_or_else(|| format!("struct#{}", id.0), |info| info.name.clone());
            let arguments = types
                .arguments(*args)
                .unwrap_or(&[])
                .iter()
                .map(|argument| format_type(types, *argument, structs, enums))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}<{arguments}>")
        }
        Some(TypeData::EnumInstance(id, args)) => {
            let name = enums
                .get(id.0 as usize)
                .map_or_else(|| format!("enum#{}", id.0), |info| info.name.clone());
            let arguments = types
                .arguments(*args)
                .unwrap_or(&[])
                .iter()
                .map(|argument| format_type(types, *argument, structs, enums))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{name}<{arguments}>")
        }
        Some(TypeData::Reference { pointee, mutable }) => format!(
            "ref {}{}",
            if *mutable { "mut " } else { "" },
            format_type(types, *pointee, structs, enums)
        ),
        Some(TypeData::Nullable(payload)) => {
            let inner = format_type(types, *payload, structs, enums);
            if matches!(types.get(*payload), Some(TypeData::Reference { .. })) {
                format!("({inner})?")
            } else {
                format!("{inner}?")
            }
        }
        Some(TypeData::Function { parameters, result }) => {
            let parameters = types
                .arguments(*parameters)
                .unwrap_or(&[])
                .iter()
                .map(|parameter| format_type(types, *parameter, structs, enums))
                .collect::<Vec<_>>()
                .join(", ");
            format!(
                "Function<({parameters}), {}>",
                format_type(types, *result, structs, enums)
            )
        }
        Some(TypeData::Buffer { element }) => {
            format!("Buffer<{}>", format_type(types, *element, structs, enums))
        }
        Some(TypeData::Vector {
            element,
            orientation,
        }) => format!(
            "Vector<{}, {:?}>",
            format_type(types, *element, structs, enums),
            orientation
        ),
        Some(TypeData::Matrix { element }) => {
            format!("Matrix<{}>", format_type(types, *element, structs, enums))
        }
        Some(TypeData::Array { element }) => {
            format!("Array<{}>", format_type(types, *element, structs, enums))
        }
        Some(TypeData::List { element }) => {
            format!("List<{}>", format_type(types, *element, structs, enums))
        }
        Some(TypeData::VectorView {
            element,
            orientation,
            mutable,
        }) => format!(
            "{}<{}, {orientation:?}>",
            if *mutable {
                "VectorViewMut"
            } else {
                "VectorView"
            },
            format_type(types, *element, structs, enums)
        ),
        Some(TypeData::MatrixView { element, mutable }) => format!(
            "{}<{}>",
            if *mutable {
                "MatrixViewMut"
            } else {
                "MatrixView"
            },
            format_type(types, *element, structs, enums)
        ),
        Some(TypeData::View { element, mutable }) => format!(
            "{}<{}>",
            if *mutable { "ViewMut" } else { "View" },
            format_type(types, *element, structs, enums)
        ),
        Some(TypeData::GenericParam(id)) => types
            .generic_name(*id)
            .map_or_else(|| format!("{id:?}"), str::to_owned),
        Some(data) => data.to_string(),
        None => types.format(ty),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldInfo {
    pub id: FieldId,
    pub owner: StructId,
    pub index: u32,
    pub name: String,
    pub ty: TypeId,
    pub offset: u64,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructInfo {
    pub id: StructId,
    pub module: ModuleId,
    pub name: String,
    pub generic_parameters: Vec<GenericParamInfo>,
    pub fields: Vec<FieldInfo>,
    pub layout: TypeLayout,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VariantPayloadInfo {
    pub index: u32,
    pub ty: TypeId,
    /// Absolute byte offset in the bootstrap typed enum envelope.
    pub offset: u64,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VariantInfo {
    pub id: VariantId,
    pub owner: EnumId,
    pub index: u32,
    pub name: String,
    pub discriminant: u32,
    pub payloads: Vec<VariantPayloadInfo>,
    pub storage_offset: u64,
    pub storage_layout: TypeLayout,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EnumInfo {
    pub id: EnumId,
    pub module: ModuleId,
    pub name: String,
    pub generic_parameters: Vec<GenericParamInfo>,
    pub variants: Vec<VariantInfo>,
    pub layout: TypeLayout,
    pub span: Span,
}

/// Closed built-in classification for equality of nominal enum values.
///
/// This deliberately does not model a general equality capability: it is the
/// shared ENUM-EQUALITY-V1 gate used by source typing and every IR verifier.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EnumEqualityClassification {
    Admitted { enum_id: EnumId, enum_type: TypeId },
    NotBothEnums,
    DifferentDeclarations { left: EnumId, right: EnumId },
    DifferentInstances { enum_id: EnumId },
    PayloadBearing { enum_id: EnumId },
    InvalidMetadata,
}

#[must_use]
pub fn classify_enum_equality(
    left: TypeId,
    right: TypeId,
    enums: &[EnumInfo],
    types: &TypeArena,
) -> EnumEqualityClassification {
    let resolve = |ty| {
        let (id, arguments) = match types.get(ty) {
            Some(TypeData::Enum(id)) => (*id, None),
            Some(TypeData::EnumInstance(id, arguments)) => (*id, Some(*arguments)),
            _ => return Ok(None),
        };
        let Some(info) = enums.get(id.0 as usize).filter(|info| info.id == id) else {
            return Err(());
        };
        let metadata_valid = match arguments {
            None => info.generic_parameters.is_empty(),
            Some(arguments) => types.arguments(arguments).is_some_and(|arguments| {
                !info.generic_parameters.is_empty()
                    && arguments.len() == info.generic_parameters.len()
                    && arguments.iter().all(|argument| types.is_valid(*argument))
            }),
        };
        metadata_valid.then_some(Some(id)).ok_or(())
    };

    let (left_id, right_id) = match (resolve(left), resolve(right)) {
        (Ok(Some(left)), Ok(Some(right))) => (left, right),
        (Ok(_), Ok(_)) => return EnumEqualityClassification::NotBothEnums,
        _ => return EnumEqualityClassification::InvalidMetadata,
    };
    if left_id != right_id {
        return EnumEqualityClassification::DifferentDeclarations {
            left: left_id,
            right: right_id,
        };
    }
    if left != right {
        return EnumEqualityClassification::DifferentInstances { enum_id: left_id };
    }
    let info = &enums[left_id.0 as usize];
    if info
        .variants
        .iter()
        .any(|variant| !variant.payloads.is_empty())
    {
        return EnumEqualityClassification::PayloadBearing { enum_id: left_id };
    }
    EnumEqualityClassification::Admitted {
        enum_id: left_id,
        enum_type: left,
    }
}

#[derive(Clone, Debug)]
pub struct DeclaredProgram {
    types: TypeArena,
    program: ParsedProgram,
    signatures: Vec<FunctionSignature>,
    names: Vec<BTreeMap<String, FunctionId>>,
    imports: Vec<BTreeMap<String, ModuleId>>,
    import_bindings: Vec<BTreeSet<String>>,
    module_names: BTreeMap<String, ModuleId>,
    aliases: Vec<BTreeMap<String, TypeId>>,
    alias_info: Vec<TypeAliasInfo>,
    structs: Vec<StructInfo>,
    enums: Vec<EnumInfo>,
    struct_names: Vec<BTreeMap<String, StructId>>,
    enum_names: Vec<BTreeMap<String, EnumId>>,
    variant_names: Vec<BTreeMap<String, VariantId>>,
    field_names: Vec<BTreeMap<String, FieldId>>,
    struct_arities: Vec<usize>,
    enum_arities: Vec<usize>,
    entry: FunctionId,
}
impl DeclaredProgram {
    #[must_use]
    pub fn signatures(&self) -> &[FunctionSignature] {
        &self.signatures
    }
    #[must_use]
    pub fn types(&self) -> &TypeArena {
        &self.types
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirLocal {
    pub id: LocalId,
    pub name: String,
    pub ty: TypeId,
    pub span: Span,
    pub parameter: bool,
    /// True only for a source local or source parameter.
    pub source_binding: bool,
    pub mutability: crate::BindingMutability,
    /// Requires stable memory because this local, or one of its fields, is borrowed.
    pub address_taken: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirParameter {
    pub local: LocalId,
    pub ty: TypeId,
    pub span: Span,
    pub mutability: crate::BindingMutability,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TypedHir {
    types: TypeArena,
    modules: Vec<ModuleInfo>,
    aliases: Vec<TypeAliasInfo>,
    structs: Vec<StructInfo>,
    enums: Vec<EnumInfo>,
    signatures: Vec<FunctionSignature>,
    instances: Vec<FunctionInstanceInfo>,
    generic_functions: Vec<GenericHirFunction>,
    functions: Vec<HirFunction>,
    entry: crate::InstanceId,
}
impl TypedHir {
    #[must_use]
    pub fn types(&self) -> &TypeArena {
        &self.types
    }
    #[must_use]
    pub fn signatures(&self) -> &[FunctionSignature] {
        &self.signatures
    }
    #[must_use]
    pub fn modules(&self) -> &[ModuleInfo] {
        &self.modules
    }
    #[must_use]
    pub fn aliases(&self) -> &[TypeAliasInfo] {
        &self.aliases
    }
    #[must_use]
    pub fn structs(&self) -> &[StructInfo] {
        &self.structs
    }
    #[must_use]
    pub fn enums(&self) -> &[EnumInfo] {
        &self.enums
    }
    #[must_use]
    pub fn functions(&self) -> &[HirFunction] {
        &self.functions
    }
    #[must_use]
    pub fn instances(&self) -> &[FunctionInstanceInfo] {
        &self.instances
    }
    #[must_use]
    pub fn generic_functions(&self) -> &[GenericHirFunction] {
        &self.generic_functions
    }
    #[must_use]
    pub const fn entry(&self) -> crate::InstanceId {
        self.entry
    }
    #[must_use]
    pub fn dump(&self) -> String {
        let type_table = self
            .types
            .entries()
            .map(|(id, _)| {
                let guarantees = [
                    Capability::Copy,
                    Capability::Relocatable,
                    Capability::Storable,
                ]
                .into_iter()
                .filter(|capability| self.types.guarantees_capability(id, *capability))
                .map(|capability| capability.to_string())
                .collect::<Vec<_>>()
                .join(" + ");
                let behaviors = BehavioralCapability::ALL.into_iter()
                    .filter(|behavior| self.types.guarantees_behavior(id, *behavior))
                    .map(|behavior| behavior.to_string()).collect::<Vec<_>>().join(", ");
                let algebraic = if self.types.guarantees_capability(id, Capability::Algebraic(AlgebraicCapability::Zero)) { "Zero" } else { "" };
                let collection = self
                    .types
                    .array_element(id)
                    .map(|element| (CollectionKind::Array, element))
                    .or_else(|| {
                        self.types
                            .matrix_element(id)
                            .map(|element| (CollectionKind::Matrix, element))
                    })
                    .or_else(|| {
                        self.types
                            .vector_element(id)
                            .map(|element| (CollectionKind::Vector, element))
                    })
                    .or_else(|| {
                        self.types
                            .list_element(id)
                            .map(|element| (CollectionKind::List, element))
                    });
                let admission = collection.map_or_else(String::new, |(kind, element)| {
                    format!(
                        "; element_requirements={:?}; element_admission={:?}",
                        kind.requirements(),
                        self.types.collection_element_admission(kind, element)
                    )
                });
                format!(
                    "  {id:?} = {}; properties={:?}; guarantees={}; structural guarantees=[{}]; behavioral guarantees=[{}]; algebraic guarantees=[{algebraic}]{}",
                    format_type(&self.types, id, &self.structs, &self.enums),
                    self.types
                        .properties(id)
                        .expect("canonical type properties"),
                    if guarantees.is_empty() {
                        "none"
                    } else {
                        &guarantees
                    },
                    guarantees,
                    behaviors,
                    admission
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let mut d = format!(
            "types (session-local):\n{type_table}\nentry: {:#?}\nmodules: {:#?}\naliases (transparent -> canonical): {:#?}\nstructs: {:#?}\nenums: {:#?}\ndeclarations: {:#?}\ngeneric HIR: {:#?}\ninstances (constraints validated before allocation): {:#?}",
            self.entry,
            self.modules,
            self.aliases,
            self.structs,
            self.enums,
            self.signatures,
            self.generic_functions,
            self.instances
        );
        if !self.types.classes().is_empty() {
            write!(d, "\nclasses: {:#?}", self.types.classes()).unwrap();
        }
        for m in &self.modules {
            let f: Vec<_> = self.functions.iter().filter(|f| f.module == m.id).collect();
            write!(
                d,
                "\nmodule {:?} `{}` functions: {f:#?}",
                m.id, m.display_name
            )
            .unwrap();
        }
        d
    }
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn into_parts(
        self,
    ) -> (
        Vec<ModuleInfo>,
        TypeArena,
        Vec<StructInfo>,
        Vec<EnumInfo>,
        Vec<FunctionInstanceInfo>,
        Vec<HirFunction>,
        crate::InstanceId,
    ) {
        (
            self.modules,
            self.types,
            self.structs,
            self.enums,
            self.instances,
            self.functions,
            self.entry,
        )
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirFunction {
    pub id: crate::InstanceId,
    pub function_id: FunctionId,
    pub module: ModuleId,
    pub parameters: Vec<HirParameter>,
    pub locals: Vec<HirLocal>,
    pub body: HirBlock,
    pub constructor_unwind: Option<crate::ConstructorUnwindPlan>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GenericHirFunction {
    pub id: FunctionId,
    pub module: ModuleId,
    pub parameters: Vec<HirParameter>,
    pub locals: Vec<HirLocal>,
    pub body: HirBlock,
    pub constructor_unwind: Option<crate::ConstructorUnwindPlan>,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FunctionInstanceInfo {
    pub id: crate::InstanceId,
    pub function_id: FunctionId,
    pub module: ModuleId,
    pub name: String,
    pub type_arguments: Vec<TypeId>,
    pub parameters: Vec<ParameterSignature>,
    pub return_type: TypeId,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirBlock {
    pub statements: Vec<HirStmt>,
    /// Owning locals destroyed on the normal lexical exit, in reverse
    /// declaration order. Early returns carry their own cleanup list.
    pub exit_drops: Vec<HirDrop>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirStmt {
    pub kind: HirStmtKind,
    pub span: Span,
    /// Provenance only; generated returns use ordinary typing and lowering.
    pub compiler_generated: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirStmtKind {
    Nop,
    Local {
        local: LocalId,
        initializer: HirExpr,
    },
    Assign {
        place: HirPlace,
        value: HirExpr,
    },
    ListPush {
        target: HirPlace,
        value: HirExpr,
        mutation: StructuralMutation,
    },
    ListReserve {
        target: HirPlace,
        requested_capacity: HirExpr,
        mutation: StructuralMutation,
    },
    StringOutput {
        function: crate::CoreFunction,
        value: HirExpr,
        newline: bool,
    },
    If {
        condition: HirExpr,
        then_block: HirBlock,
        else_block: Option<HirBlock>,
    },
    While {
        condition: HirExpr,
        body: HirBlock,
    },
    /// ITERATION-V1 inclusive range loop over canonical int64.
    ForRange {
        loop_id: LoopId,
        binding: LocalId,
        item_type: TypeId,
        start: HirExpr,
        step: HirExpr,
        end: HirExpr,
        step_is_implicit: bool,
        body: HirBlock,
    },
    /// Index loop over an exact Array<T> or List<T>.
    ForCollection {
        loop_id: LoopId,
        binding: LocalId,
        iterable_type: TypeId,
        item_type: TypeId,
        binding_type: TypeId,
        category: IterationBindingCategory,
        source: CollectionIterationSource,
        structural_borrow: bool,
        body: HirBlock,
    },
    Match {
        mode: MatchMode,
        scrutinee: HirExpr,
        enum_type: TypeId,
        enum_id: EnumId,
        arms: Vec<HirMatchArm>,
    },
    Return {
        value: HirExpr,
        drops: Vec<HirDrop>,
    },
    Break {
        drops: Vec<HirDrop>,
    },
    Continue {
        drops: Vec<HirDrop>,
    },
    Throw {
        value: HirExpr,
        class: ClassId,
        transfer: bool,
        drops: Vec<HirDrop>,
    },
    Rethrow {
        catch: CatchId,
        drops: Vec<HirDrop>,
    },
    Try {
        body: HirBlock,
        catches: Vec<HirCatch>,
        finally: Option<HirFinally>,
    },
}

/// Ownership/provenance form of a collection iteration operand.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CollectionIterationSource {
    /// An existing collection place remains borrowed for the complete loop.
    Borrowed(HirPlace),
    /// A completed owning value is transferred into this hidden loop root.
    Temporary { root: LocalId, initializer: HirExpr },
}

/// Source-visible category of the element binding.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IterationBindingCategory {
    CopyValue,
    SharedElementBorrow,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirCatch {
    pub id: CatchId,
    pub class: ClassId,
    pub binding: LocalId,
    pub body: HirBlock,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirFinally {
    pub id: FinallyId,
    pub body: HirBlock,
    pub span: Span,
}

/// Semantic collection mutation identity. `effect()` distinguishes backing
/// relocation from initialized-range invalidation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StructuralMutation {
    Push,
    Reserve,
    Pop,
    SwapRemove,
    Remove,
}

/// Small collection effect vocabulary; writable does not imply reallocation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MutationEffect {
    ElementMutation,
    StableStructuralMutation,
    PotentiallyRelocatingMutation,
}

/// Logical slots invalidated independently of backing-storage stability.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InvalidationShape {
    /// The requested element and the previous tail (one slot when equal).
    IndexAndTail,
    /// Every old slot at or after the HIR removal index.
    SuffixFrom,
}

impl StructuralMutation {
    #[must_use]
    pub const fn effect(self) -> MutationEffect {
        match self {
            Self::Pop | Self::SwapRemove | Self::Remove => MutationEffect::StableStructuralMutation,
            Self::Push | Self::Reserve => MutationEffect::PotentiallyRelocatingMutation,
        }
    }
}

impl HirStmtKind {
    /// Collection effects describe storage stability. Whole-root replacement
    /// remains an ownership operation, outside this collection effect API.
    #[must_use]
    pub fn mutation_effect(&self) -> Option<MutationEffect> {
        match self {
            Self::Assign { place, .. }
                if place
                    .projections
                    .iter()
                    .any(|projection| matches!(projection, HirPlaceProjection::Index { .. })) =>
            {
                Some(MutationEffect::ElementMutation)
            }
            Self::ListPush { mutation, .. } | Self::ListReserve { mutation, .. } => {
                Some(mutation.effect())
            }
            _ => None,
        }
    }
}

/// Fully resolved ownership behavior of an enum match.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MatchMode {
    Value,
    SharedRef,
    MutableRef,
}

/// Normal-path cleanup obligation synthesized by ownership analysis.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirDrop {
    Unconditional(LocalId),
    Conditional(LocalId),
}

impl HirDrop {
    #[must_use]
    pub const fn local(self) -> LocalId {
        match self {
            Self::Unconditional(local) | Self::Conditional(local) => local,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirMatchArm {
    pub variant_id: VariantId,
    pub bindings: Vec<HirMatchBinding>,
    pub body: HirBlock,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirMatchBinding {
    pub local: LocalId,
    pub payload_index: u32,
    pub ty: TypeId,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirPlace {
    pub base: HirPlaceBase,
    pub projections: Vec<HirPlaceProjection>,
    pub ty: TypeId,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirPlaceProjection {
    Field(FieldId),
    Index {
        index: Box<HirExpr>,
        /// Present exactly for `OneBased2D` Matrix projections.
        column: Option<Box<HirExpr>>,
        element_type: TypeId,
        checked: bool,
        semantics: IndexSemantics,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirPlaceBase {
    Local(LocalId),
    Dereference {
        reference: Box<HirExpr>,
        mutable: bool,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirExpr {
    pub kind: HirExprKind,
    pub ty: TypeId,
    pub span: Span,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct NonNullProofId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NullablePayloadAccess {
    Copy,
    Borrow,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum NullState {
    Unknown,
    Null,
    NonNull,
}

fn nullable_loop_expression_effects(
    expression: &AstExpr,
    written_roots: &mut BTreeSet<String>,
    has_call: &mut bool,
) {
    match &expression.kind {
        AstExprKind::Call { args, .. }
        | AstExprKind::QualifiedCall { args, .. }
        | AstExprKind::VariantCall { args, .. } => {
            *has_call = true;
            for argument in args {
                nullable_loop_expression_effects(argument, written_roots, has_call);
            }
        }
        AstExprKind::MethodCall { receiver, args, .. } => {
            *has_call = true;
            nullable_loop_expression_effects(receiver, written_roots, has_call);
            for argument in args {
                nullable_loop_expression_effects(argument, written_roots, has_call);
            }
        }
        AstExprKind::Unary { op, operand } => {
            if *op == AstUnaryOp::BorrowMutable
                && let AstExprKind::Name(name) = &operand.kind
            {
                written_roots.insert(name.clone());
            }
            nullable_loop_expression_effects(operand, written_roots, has_call);
        }
        AstExprKind::Binary { left, right, .. } => {
            nullable_loop_expression_effects(left, written_roots, has_call);
            nullable_loop_expression_effects(right, written_roots, has_call);
        }
        AstExprKind::Range { start, step, end } => {
            nullable_loop_expression_effects(start, written_roots, has_call);
            if let Some(step) = step {
                nullable_loop_expression_effects(step, written_roots, has_call);
            }
            nullable_loop_expression_effects(end, written_roots, has_call);
        }
        AstExprKind::CollectionLiteral(elements) => {
            for element in elements {
                nullable_loop_expression_effects(element, written_roots, has_call);
            }
        }
        AstExprKind::MathematicalLiteral { rows } => {
            for element in rows.iter().flatten() {
                nullable_loop_expression_effects(element, written_roots, has_call);
            }
        }
        AstExprKind::Interpolation(fragments) => {
            for fragment in fragments {
                if let crate::AstInterpolationFragment::Hole { expression, .. } = fragment {
                    nullable_loop_expression_effects(expression, written_roots, has_call);
                }
            }
        }
        AstExprKind::Field { base, .. } => {
            nullable_loop_expression_effects(base, written_roots, has_call);
        }
        AstExprKind::Index { base, indices } => {
            nullable_loop_expression_effects(base, written_roots, has_call);
            for index in indices {
                nullable_loop_expression_effects(index, written_roots, has_call);
            }
        }
        AstExprKind::Integer(_)
        | AstExprKind::Float(_)
        | AstExprKind::String(_)
        | AstExprKind::Char(_)
        | AstExprKind::Bool(_)
        | AstExprKind::Null
        | AstExprKind::Name(_)
        | AstExprKind::QualifiedName { .. } => {}
    }
}

fn nullable_loop_block_effects(
    block: &AstBlock,
    written_roots: &mut BTreeSet<String>,
    has_call: &mut bool,
) {
    for statement in &block.statements {
        match &statement.kind {
            AstStmtKind::Local { initializer, .. } => {
                nullable_loop_expression_effects(initializer, written_roots, has_call);
            }
            AstStmtKind::Assign { place, value } => {
                if let AstExprKind::Name(name) = &place.kind {
                    written_roots.insert(name.clone());
                }
                nullable_loop_expression_effects(place, written_roots, has_call);
                nullable_loop_expression_effects(value, written_roots, has_call);
            }
            AstStmtKind::Expr(expression) => {
                nullable_loop_expression_effects(expression, written_roots, has_call);
            }
            AstStmtKind::If {
                condition,
                then_block,
                else_block,
            } => {
                nullable_loop_expression_effects(condition, written_roots, has_call);
                nullable_loop_block_effects(then_block, written_roots, has_call);
                if let Some(else_block) = else_block {
                    nullable_loop_block_effects(else_block, written_roots, has_call);
                }
            }
            AstStmtKind::While { condition, body } => {
                nullable_loop_expression_effects(condition, written_roots, has_call);
                nullable_loop_block_effects(body, written_roots, has_call);
            }
            AstStmtKind::ForIn { iterable, body, .. } => {
                nullable_loop_expression_effects(iterable, written_roots, has_call);
                nullable_loop_block_effects(body, written_roots, has_call);
            }
            AstStmtKind::Match {
                scrutinee, arms, ..
            } => {
                nullable_loop_expression_effects(scrutinee, written_roots, has_call);
                for arm in arms {
                    nullable_loop_block_effects(&arm.body, written_roots, has_call);
                }
            }
            AstStmtKind::Return(value) | AstStmtKind::Throw(value) => {
                if let Some(value) = value {
                    nullable_loop_expression_effects(value, written_roots, has_call);
                }
            }
            AstStmtKind::Try {
                body,
                catches,
                finally,
            } => {
                nullable_loop_block_effects(body, written_roots, has_call);
                for catch in catches {
                    nullable_loop_block_effects(&catch.body, written_roots, has_call);
                }
                if let Some(finally) = finally {
                    nullable_loop_block_effects(finally, written_roots, has_call);
                }
            }
            AstStmtKind::Break | AstStmtKind::Continue => {}
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CallBorrowOrigin {
    Implicit,
    Explicit,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CallBorrowSource {
    Place(HirPlace),
    Temporary(Box<HirExpr>),
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FloatValue {
    Float32(u32),
    Float64(u64),
}
/// Ordered shape compatibility guards, raising `ShapeMismatch` before allocation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MathShapeCheck {
    /// One exact dimension equality, with no orientation conversion.
    VectorDimension,
    /// Exact row equality followed by exact column equality.
    MatrixRowsThenColumns,
    /// Matrix columns equal the right Column dimension.
    MatrixColumnsVectorDimension,
    /// Left Row dimension equals Matrix rows.
    VectorDimensionMatrixRows,
    /// Left Matrix columns equal right Matrix rows.
    MatrixColumnsMatrixRows,
}
/// Logical Matrix axis, independent of physical strides.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MatrixProductExtent {
    Rows,
    Columns,
}
/// Source operand position, used by scaling and algebraic extent selectors.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScalarSide {
    Left,
    Right,
}
/// Declarative element operation; behavioral metadata exists only before instantiation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MathElementOp {
    Concrete(HirBinaryOp),
    Behavioral(BehavioralCapability),
}
/// Closed semantic products with distinct orientation and result-shape contracts.
/// Computational loop forms are selected only after scalar concretization.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AlgebraicProductKind {
    /// Two-dimensional map of ordered reductions producing an owning Matrix.
    MatrixMatrix {
        shape_check: MathShapeCheck,
        output_rows: (ScalarSide, MatrixProductExtent),
        output_columns: (ScalarSide, MatrixProductExtent),
        contraction_extent: (ScalarSide, MatrixProductExtent),
        accumulate_op: MathElementOp,
        zero: Box<HirExpr>,
    },
    /// Closed map of ordered reductions producing an owning oriented Vector.
    MatrixVector {
        matrix_side: ScalarSide,
        shape_check: MathShapeCheck,
        result_extent: MatrixProductExtent,
        contraction_extent: MatrixProductExtent,
        accumulate_op: MathElementOp,
        zero: Box<HirExpr>,
    },
    /// Row × Column scalar reduction, including canonical Zero for dimension 0.
    Inner {
        shape_check: MathShapeCheck,
        accumulate_op: MathElementOp,
        zero: Box<HirExpr>,
    },
    /// Column × Row owning Matrix map; no accumulation or Zero requirement.
    Outer {
        rows: ScalarSide,
        columns: ScalarSide,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirExprKind {
    /// Compiler materialization of the source-level no-result value.
    Unit,
    /// Resolved class identities, ownership uses and direct member effects.
    Class(Box<ClassOp<HirExpr>>),
    /// Fundamental immutable string lifecycle and content operations.
    String(Box<crate::StringOp<HirExpr>>),
    /// Canonical standard-library text operations, separate from core `StringOp`.
    Text {
        call_site: CallSiteId,
        op: Box<crate::TextOp<HirExpr>>,
    },
    /// A fully resolved, canonically identified Core function call.
    Core(Box<crate::CoreCall<HirExpr>>),
    AlgebraicValue {
        capability: AlgebraicCapability,
    },
    /// Native algebraic multiplication; the kind fixes the exact result family.
    AlgebraicProduct {
        left: Box<HirExpr>,
        right: Box<HirExpr>,
        element_type: TypeId,
        product_op: MathElementOp,
        product: AlgebraicProductKind,
    },
    /// Parametric homogeneous T op T -> T; behavior is the sole operator tag.
    /// Monomorphization must reify this before concrete HIR crosses into MIR.
    CapabilityBinary {
        behavior: BehavioralCapability,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
    VectorScalarMultiply {
        left: Box<HirExpr>,
        right: Box<HirExpr>,
        scalar_side: ScalarSide,
        element_type: TypeId,
        op: MathElementOp,
        orientation: crate::types::Orientation,
    },
    MatrixScalarMultiply {
        left: Box<HirExpr>,
        right: Box<HirExpr>,
        scalar_side: ScalarSide,
        element_type: TypeId,
        op: MathElementOp,
    },
    /// Read operands through logical strides; exact shape, fresh owning result.
    VectorElementwiseBinary {
        shape_check: MathShapeCheck,
        source_op: AstBinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
        element_type: TypeId,
        op: MathElementOp,
        orientation: crate::types::Orientation,
    },
    /// Logical 2D reads; rows and columns must match before allocation.
    MatrixElementwiseBinary {
        shape_check: MathShapeCheck,
        source_op: AstBinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
        element_type: TypeId,
        op: MathElementOp,
    },
    Int(i128),
    Float(FloatValue),
    Bool(bool),
    NullableNull {
        nullable_type: TypeId,
    },
    NullableInject {
        payload: Box<HirExpr>,
        nullable_type: TypeId,
    },
    NullableIsNull {
        operand: Box<HirExpr>,
    },
    NullablePayload {
        source: HirPlace,
        proof: NonNullProofId,
        access: NullablePayloadAccess,
    },
    ShortCircuitAnd {
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
    ShortCircuitOr {
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
    LogicalNot {
        operand: Box<HirExpr>,
    },
    /// Exact address of one visible top-level Aether function.
    FunctionRef {
        target: HirCallTarget,
        function_type: TypeId,
    },
    Local(LocalId),
    /// Explicit consuming use of a move-only local.
    Move(LocalId),
    Load(HirPlace),
    Borrow {
        place: HirPlace,
        mutable: bool,
    },
    /// Exact `T -> ref T` adaptation confined to one resolved call argument.
    CallScopedSharedBorrow {
        call_site: CallSiteId,
        argument_index: u32,
        pointee_type: TypeId,
        reference_type: TypeId,
        source: CallBorrowSource,
        origin: CallBorrowOrigin,
    },
    BufferInit {
        element_type: TypeId,
        length: Box<HirExpr>,
        initial: Box<HirExpr>,
    },
    /// Consumes one owner and transfers its unchanged {ptr, dimension} descriptor.
    /// Source/result `TypeIds` encode the exact element and opposite orientations.
    VectorTranspose {
        operand: Box<HirExpr>,
        source_type: TypeId,
    },
    /// Expected-type-resolved `[...]` mathematical construction.
    MatrixInit {
        rows: u64,
        columns: u64,
        /// Retained source row boundaries, checked independently; no runtime field.
        row_ends: Vec<u64>,
        element_type: TypeId,
        elements: Vec<HirExpr>,
    },
    VectorInit {
        element_type: TypeId,
        elements: Vec<HirExpr>,
    },
    /// Expected-type-resolved `{...}` collection construction.
    ArrayInit {
        element_type: TypeId,
        elements: Vec<HirExpr>,
    },
    /// Fixed-length fill construction `Array<T>(length, fill)`.
    ArrayFill {
        element_type: TypeId,
        length: Box<HirExpr>,
        initial: Box<HirExpr>,
    },
    /// Mathematical `dimension(vector-place)` query.
    MatrixRows {
        source: HirPlace,
    },
    MatrixColumns {
        source: HirPlace,
    },
    VectorDimension {
        source: HirPlace,
    },
    /// Bootstrap `length(array-place)` query.
    ArrayLength {
        source: HirPlace,
    },
    /// Expected-type-resolved dynamic collection construction.
    ListInit {
        element_type: TypeId,
        elements: Vec<HirExpr>,
    },
    ListLength {
        source: HirPlace,
    },
    ListCapacity {
        source: HirPlace,
    },
    ListSwapRemove {
        source: HirPlace,
        index: Box<HirExpr>,
        element_type: TypeId,
        effect: MutationEffect,
        invalidation: InvalidationShape,
    },
    ListRemove {
        source: HirPlace,
        index: Box<HirExpr>,
        element_type: TypeId,
        effect: MutationEffect,
        invalidation: InvalidationShape,
    },
    ListPop {
        source: HirPlace,
        element_type: TypeId,
        effect: MutationEffect,
    },
    /// Borrow the source backing. Source Place and descriptor copy/use chains
    /// retain provenance; the closed recipe is independently verified.
    MatrixAxisVectorView {
        source: HirPlace,
        fixed_index: Box<HirExpr>,
        axis: crate::types::Orientation,
        mutable: bool,
        descriptor: crate::types::MatrixAxisVectorViewDescriptor,
    },
    /// Borrow/transpose an oriented vector with a closed stride recipe.
    VectorView {
        source: HirPlace,
        mutable: bool,
        transpose: bool,
        descriptor: crate::types::VectorViewDescriptor,
    },
    /// Borrow 2D backing with an independently verified shape/stride recipe.
    MatrixView {
        source: HirPlace,
        mutable: bool,
        transpose: bool,
        descriptor: crate::types::MatrixViewDescriptor,
    },
    View {
        source: HirPlace,
        mutable: bool,
    },
    Call {
        call_site: CallSiteId,
        callee: HirCallTarget,
        type_arguments: Vec<TypeId>,
        args: Vec<HirCallArgument>,
    },
    /// Call through a first-class non-capturing function pointer.
    IndirectCall {
        call_site: CallSiteId,
        callee: Box<HirExpr>,
        args: Vec<HirExpr>,
        signature: TypeId,
    },
    StructInit {
        struct_id: StructId,
        fields: Vec<(FieldId, HirExpr)>,
    },
    EnumInit {
        enum_id: EnumId,
        variant_id: VariantId,
        payloads: Vec<HirExpr>,
    },
    Coerce {
        kind: CoercionKind,
        operand: Box<HirExpr>,
    },
    ExplicitCast {
        kind: CastKind,
        source_type: TypeId,
        target_type: TypeId,
        operand: Box<HirExpr>,
    },
    Unary {
        op: HirUnaryOp,
        operand: Box<HirExpr>,
    },
    Binary {
        op: HirBinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirCallArgument {
    pub binding: LocalId,
    pub initializer: HirExpr,
    pub ty: TypeId,
    pub origin: HirCallArgumentOrigin,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirCallArgumentOrigin {
    Explicit {
        source_span: Span,
    },
    Defaulted {
        declaration: FunctionId,
        parameter_index: u32,
        default_span: Span,
        call_span: Span,
    },
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirCallTarget {
    Declaration(FunctionId),
    Instance(crate::InstanceId),
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CoercionKind {
    SignExtend,
    ZeroExtend,
    FloatExtend,
}
/// Value-conversion semantics selected completely by HIR.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CastKind {
    Identity,
    IntegerExtendSigned,
    IntegerExtendUnsigned,
    IntegerNarrowChecked,
    IntegerReencode,
    IntegerSignednessChecked,
    SignedIntegerToFloat,
    UnsignedIntegerToFloat,
    FloatToSignedIntegerChecked,
    FloatToUnsignedIntegerChecked,
    FloatExtend,
    FloatTruncate,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirUnaryOp {
    NegateIntegerChecked,
    NegateFloat,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HirBinaryOp {
    AddIntegerChecked,
    SubtractIntegerChecked,
    MultiplyIntegerChecked,
    DivideIntegerSignedChecked,
    DivideIntegerUnsignedChecked,
    RemainderIntegerSignedChecked,
    RemainderIntegerUnsignedChecked,
    AddFloat,
    SubtractFloat,
    MultiplyFloat,
    DivideFloat,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Equal,
    NotEqual,
}

fn merge_package_tables<T: Copy>(program: &ParsedProgram, tables: &mut [BTreeMap<String, T>]) {
    let mut package_tables = BTreeMap::<PackageId, BTreeMap<String, T>>::new();
    for module in &program.modules {
        package_tables
            .entry(module.info.package)
            .or_default()
            .extend(
                tables[module.info.id.0 as usize]
                    .iter()
                    .map(|(name, id)| (name.clone(), *id)),
            );
    }
    for module in &program.modules {
        tables[module.info.id.0 as usize] = package_tables[&module.info.package].clone();
    }
}

pub fn collect_signatures(ast: ParsedAst) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    let source = ast.functions.first().map_or(SourceId(0), |f| f.span.source);
    let package_key = ast.package().map_or(PackageKey::Anonymous, |package| {
        PackageKey::named(OriginKey::Project, PackagePath(package.path.clone()))
    });
    let display_name = if matches!(&package_key, PackageKey::Anonymous) {
        package_key.display()
    } else {
        "main".into()
    };
    collect_program_signatures(ParsedProgram {
        modules: vec![ParsedModule {
            info: ModuleInfo {
                id: ModuleId(0),
                key: SourceUnitKey {
                    package: package_key,
                    logical_source: LogicalSourceKey("<memory>".into()),
                },
                package: PackageId(0),
                display_name,
                source,
                source_name: "<memory>".into(),
                imports: vec![],
                semantic_dependencies: BTreeSet::new(),
            },
            ast,
        }],
        entry: ModuleId(0),
    })
}
pub fn collect_program_signatures(
    mut program: ParsedProgram,
) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    classes::inject_exception_core(&mut program)?;
    classes::expand_methods(&mut program)?;
    validate_program(&program)?;
    let representatives = program
        .modules
        .iter()
        .fold(BTreeMap::new(), |mut map, module| {
            map.entry(module.info.package).or_insert(module.info.id);
            map
        });
    let module_names: BTreeMap<String, ModuleId> = program
        .modules
        .iter()
        .filter_map(|module| {
            module
                .info
                .key
                .package
                .named_parts()
                .map(|(_, path)| (path.source(), representatives[&module.info.package]))
        })
        .collect();
    let imports: Vec<BTreeMap<String, ModuleId>> = program
        .modules
        .iter()
        .map(|module| {
            let mut visible = BTreeMap::new();
            for grant in &module.info.imports {
                let (grant_origin, grant_path) = grant
                    .target
                    .named_parts()
                    .expect("validated import target is named");
                for candidate in &program.modules {
                    if candidate.info.key.package.named_parts().is_some_and(
                        |(candidate_origin, candidate_path)| {
                            candidate_origin == grant_origin
                                && candidate_path.starts_with(grant_path)
                        },
                    ) {
                        let candidate_path = candidate
                            .info
                            .key
                            .package
                            .named_parts()
                            .expect("filtered named package")
                            .1;
                        let suffix = &candidate_path.0[grant_path.0.len()..];
                        let spelling = if let Some(alias) = &grant.alias {
                            std::iter::once(alias.as_str())
                                .chain(suffix.iter().map(String::as_str))
                                .collect::<Vec<_>>()
                                .join(".")
                        } else {
                            candidate_path.source()
                        };
                        visible.insert(spelling, representatives[&candidate.info.package]);
                    }
                }
            }
            visible
        })
        .collect();
    let import_bindings = program
        .modules
        .iter()
        .map(|module| {
            module
                .info
                .imports
                .iter()
                .map(|grant| {
                    grant.alias.clone().unwrap_or_else(|| {
                        grant
                            .target
                            .named_parts()
                            .expect("validated import target is named")
                            .1
                            .0[0]
                            .clone()
                    })
                })
                .collect::<BTreeSet<_>>()
        })
        .collect::<Vec<_>>();

    // One fail-closed top-level namespace per package, independent of which
    // source unit contributed a declaration.
    let mut package_declarations = BTreeMap::<(PackageId, String), (&str, ModuleId, Span)>::new();
    for module in &program.modules {
        for (kind, name, span) in module
            .ast
            .aliases()
            .iter()
            .map(|d| ("alias", &d.name, d.span))
            .chain(
                module
                    .ast
                    .structs()
                    .iter()
                    .map(|d| ("struct", &d.name, d.span)),
            )
            .chain(
                module
                    .ast
                    .classes()
                    .iter()
                    .map(|d| ("class", &d.name, d.span)),
            )
            .chain(module.ast.enums().iter().map(|d| ("enum", &d.name, d.span)))
            .chain(
                module
                    .ast
                    .interfaces()
                    .iter()
                    .map(|d| ("interface", &d.name, d.span)),
            )
            .chain(
                module
                    .ast
                    .functions()
                    .iter()
                    .map(|d| ("function", &d.name, d.span)),
            )
        {
            if let Some((previous_kind, previous_module, previous_span)) = package_declarations
                .insert(
                    (module.info.package, name.clone()),
                    (kind, module.info.id, span),
                )
            {
                return Err(vec![src(
                    Diagnostic::new(
                        if kind == "function" && previous_kind == "function" {
                            "E0211"
                        } else if kind == "alias" && previous_kind == "alias" {
                            "E0225"
                        } else {
                            "E0240"
                        },
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate package member `{name}` ({previous_kind} in {} at {}..{}, {kind} in {})",
                            program.modules[previous_module.0 as usize].info.source_name,
                            previous_span.start,
                            previous_span.end,
                            module.info.source_name
                        ),
                        Some(span),
                    ),
                    module,
                )]);
            }
        }
    }
    for module in &program.modules {
        for import in &module.info.imports {
            let binding = import.alias.clone().unwrap_or_else(|| {
                import
                    .target
                    .named_parts()
                    .expect("validated import target is named")
                    .1
                    .0[0]
                    .clone()
            });
            if package_declarations.contains_key(&(module.info.package, binding.clone())) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0235",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "namespace binding `{binding}` conflicts with a member of package `{}`",
                            module.info.key.package.display()
                        ),
                        Some(import.span),
                    ),
                    module,
                )]);
            }
        }
    }

    // A source unit still owns imports/provenance, while names are collected
    // package-wide before bodies.
    // call-like spelling has exactly one semantic interpretation.
    for module in &program.modules {
        let mut declarations = BTreeMap::new();
        for (kind, name, span) in module
            .ast
            .aliases()
            .iter()
            .map(|d| ("alias", &d.name, d.span))
            .chain(
                module
                    .ast
                    .structs()
                    .iter()
                    .map(|d| ("struct", &d.name, d.span)),
            )
            .chain(
                module
                    .ast
                    .classes()
                    .iter()
                    .map(|d| ("class", &d.name, d.span)),
            )
            .chain(module.ast.enums().iter().map(|d| ("enum", &d.name, d.span)))
            .chain(
                module
                    .ast
                    .interfaces()
                    .iter()
                    .map(|d| ("interface", &d.name, d.span)),
            )
            .chain(
                module
                    .ast
                    .functions()
                    .iter()
                    .map(|d| ("function", &d.name, d.span)),
            )
        {
            let previous = declarations.insert(name.clone(), kind);
            if name == "Function"
                || builtin(name).is_some()
                || intrinsic_type_arity(name).is_some()
                || previous.is_some()
            {
                let code = match previous {
                    Some("function") if kind == "function" => "E0211",
                    Some("alias") if kind == "alias" => "E0225",
                    _ if builtin(name).is_some() && kind == "function" => "E0211",
                    _ if builtin(name).is_some() && kind == "alias" => "E0225",
                    _ => "E0240",
                };
                return Err(vec![src(
                    Diagnostic::new(
                        code,
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("conflicting top-level declaration `{name}` ({kind})"),
                        Some(span),
                    ),
                    module,
                )]);
            }
        }
    }
    // Nominal identities exist before any field/signature type is resolved.
    let mut struct_names = vec![BTreeMap::new(); program.modules.len()];
    let mut struct_decls = Vec::new();
    for module in &program.modules {
        for declaration in module.ast.structs() {
            let id = StructId(struct_decls.len() as u32);
            struct_names[module.info.id.0 as usize].insert(declaration.name.clone(), id);
            struct_decls.push((id, module.info.id, declaration));
        }
    }
    merge_package_tables(&program, &mut struct_names);

    let mut enum_names = vec![BTreeMap::new(); program.modules.len()];
    let mut enum_decls = Vec::new();
    for module in &program.modules {
        for declaration in module.ast.enums() {
            let id = EnumId(enum_decls.len() as u32);
            enum_names[module.info.id.0 as usize].insert(declaration.name.clone(), id);
            enum_decls.push((id, module.info.id, declaration));
        }
    }
    merge_package_tables(&program, &mut enum_names);
    let struct_arities = struct_decls
        .iter()
        .map(|(_, _, declaration)| declaration.generic_parameters.len())
        .collect::<Vec<_>>();
    let enum_arities = enum_decls
        .iter()
        .map(|(_, _, declaration)| declaration.generic_parameters.len())
        .collect::<Vec<_>>();

    // Allocation order is deterministic for dumps but has no semantic or ABI
    // meaning. Declaration identities make nominality explicit in TypeData.
    let mut types = TypeArena::new();
    classes::register_identities(&program, &mut types);
    for module in &program.modules {
        for i in module.ast.interfaces() {
            let id = crate::InterfaceId(types.interfaces.len() as u32);
            types.register_interface_definition(crate::InterfaceInfo {
                id,
                module: module.info.id,
                name: i.name.clone(),
                public: i.public,
                requirements: Vec::new(),
                span: i.span,
            });
            types.intern(TypeData::Interface(id));
            types.intern(TypeData::InterfaceKeepalive {
                interface: id,
                mutable: false,
            });
            types.intern(TypeData::InterfaceKeepalive {
                interface: id,
                mutable: true,
            });
        }
    }
    for (id, _, _) in &struct_decls {
        types.intern(TypeData::Struct(*id));
    }
    for (id, _, _) in &enum_decls {
        types.intern(TypeData::Enum(*id));
    }

    let mut aliases = vec![BTreeMap::new(); program.modules.len()];
    let mut alias_info = vec![];
    for module in &program.modules {
        let mut declarations = BTreeMap::new();
        for a in module.ast.aliases() {
            declarations.insert(a.name.clone(), a);
        }
        let mut state = BTreeMap::new();
        for name in declarations.keys() {
            resolve_alias(
                name,
                module,
                &declarations,
                &struct_names,
                &enum_names,
                &imports,
                &module_names,
                &mut types,
                &struct_arities,
                &enum_arities,
                &mut state,
                &mut aliases[module.info.id.0 as usize],
                &mut alias_info,
            )?;
        }
    }
    merge_package_tables(&program, &mut aliases);

    let mut structs = Vec::with_capacity(struct_decls.len());
    let mut field_names = Vec::with_capacity(struct_decls.len());
    let mut next_field = 0_u32;
    for (id, module_id, declaration) in struct_decls {
        let module = &program.modules[module_id.0 as usize];
        let generic_parameters = collect_generic_parameters(
            GenericOwner::Struct(id),
            &declaration.generic_parameters,
            &mut types,
        )
        .map_err(|diagnostic| vec![src(diagnostic, module)])?;
        let generic_scope = generic_parameters
            .iter()
            .map(|parameter| (parameter.name.clone(), parameter.ty))
            .collect::<BTreeMap<_, _>>();
        let mut seen = BTreeMap::new();
        let mut fields = Vec::new();
        for (index, field) in declaration.fields.iter().enumerate() {
            if seen.contains_key(&field.name) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0241",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate field `{}` in struct `{}`",
                            field.name, declaration.name
                        ),
                        Some(field.span),
                    ),
                    module,
                )]);
            }
            let ty = resolve_type_in_module(
                &field.ty,
                module_id,
                &aliases,
                &struct_names,
                &enum_names,
                &imports,
                &module_names,
                &mut types,
                &generic_scope,
                &struct_arities,
                &enum_arities,
            )
            .map_err(|d| vec![src(d, module)])?;
            if types.contains_view(ty) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0285",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "Vertical-10 views cannot be stored in user structs",
                        Some(field.span),
                    ),
                    module,
                )]);
            }
            if types.contains_function(ty) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0357",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        "Function fields are not supported in FUNCTION-VALUES-V1",
                        Some(field.span),
                    ),
                    module,
                )]);
            }
            if ty == TypeId::VOID {
                return Err(vec![src(
                    type_error("void is not storable in a struct field", field.span),
                    module,
                )]);
            }
            if types.contains_reference(ty) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0274",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "Vertical-9 references cannot be stored in struct fields",
                        Some(field.span),
                    ),
                    module,
                )]);
            }
            let field_id = FieldId(next_field);
            next_field += 1;
            seen.insert(field.name.clone(), field_id);
            fields.push(FieldInfo {
                id: field_id,
                owner: id,
                index: index as u32,
                name: field.name.clone(),
                ty,
                offset: 0,
                span: field.span,
            });
        }
        field_names.push(seen);
        structs.push(StructInfo {
            id,
            module: module_id,
            name: declaration.name.clone(),
            generic_parameters,
            fields,
            layout: TypeLayout { size: 0, align: 1 },
            span: declaration.span,
        });
    }

    let mut enums = Vec::with_capacity(enum_decls.len());
    let mut variant_names = Vec::with_capacity(enum_decls.len());
    for (id, module_id, declaration) in enum_decls {
        let module = &program.modules[module_id.0 as usize];
        let generic_parameters = collect_generic_parameters(
            GenericOwner::Enum(id),
            &declaration.generic_parameters,
            &mut types,
        )
        .map_err(|diagnostic| vec![src(diagnostic, module)])?;
        let generic_scope = generic_parameters
            .iter()
            .map(|parameter| (parameter.name.clone(), parameter.ty))
            .collect::<BTreeMap<_, _>>();
        let mut seen = BTreeMap::new();
        let mut variants = Vec::new();
        for (index, variant) in declaration.variants.iter().enumerate() {
            if seen.contains_key(&variant.name) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0251",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate variant `{}` in enum `{}`",
                            variant.name, declaration.name
                        ),
                        Some(variant.span),
                    ),
                    module,
                )]);
            }
            let variant_id = VariantId {
                enum_id: id,
                index: index as u32,
            };
            seen.insert(variant.name.clone(), variant_id);
            let payloads = variant
                .payloads
                .iter()
                .enumerate()
                .map(|(payload_index, ty)| {
                    resolve_type_in_module(
                        ty,
                        module_id,
                        &aliases,
                        &struct_names,
                        &enum_names,
                        &imports,
                        &module_names,
                        &mut types,
                        &generic_scope,
                        &struct_arities,
                        &enum_arities,
                    )
                    .map(|resolved| VariantPayloadInfo {
                        index: payload_index as u32,
                        ty: resolved,
                        offset: 0,
                        span: ty.span,
                    })
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|d| vec![src(d, module)])?;
            if let Some(payload) = payloads
                .iter()
                .find(|payload| types.contains_view(payload.ty))
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0286",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "borrowed views cannot be stored in enum payloads",
                        Some(payload.span),
                    ),
                    module,
                )]);
            }
            if let Some(payload) = payloads
                .iter()
                .find(|payload| types.contains_function(payload.ty))
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0357",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        "Function enum payloads are not supported in FUNCTION-VALUES-V1",
                        Some(payload.span),
                    ),
                    module,
                )]);
            }
            if let Some(payload) = payloads.iter().find(|payload| payload.ty == TypeId::VOID) {
                return Err(vec![src(
                    type_error("void is not storable in an enum payload", payload.span),
                    module,
                )]);
            }
            if let Some(payload) = payloads
                .iter()
                .find(|payload| types.contains_reference(payload.ty))
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0275",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "Vertical-9 references cannot be stored in enum payloads",
                        Some(payload.span),
                    ),
                    module,
                )]);
            }
            variants.push(VariantInfo {
                id: variant_id,
                owner: id,
                index: index as u32,
                name: variant.name.clone(),
                discriminant: index as u32,
                payloads,
                storage_offset: 0,
                storage_layout: TypeLayout { size: 0, align: 1 },
                span: variant.span,
            });
        }
        variant_names.push(seen);
        enums.push(EnumInfo {
            id,
            module: module_id,
            name: declaration.name.clone(),
            generic_parameters,
            variants,
            layout: TypeLayout { size: 0, align: 1 },
            span: declaration.span,
        });
    }
    for info in &structs {
        types.register_struct_properties(
            info.id,
            info.generic_parameters
                .iter()
                .map(|parameter| parameter.id)
                .collect(),
            info.fields.iter().map(|field| field.ty).collect(),
        );
    }
    for info in &enums {
        types.register_enum_properties(
            info.id,
            info.generic_parameters
                .iter()
                .map(|parameter| parameter.id)
                .collect(),
            info.variants
                .iter()
                .map(|variant| variant.payloads.iter().map(|payload| payload.ty).collect())
                .collect(),
        );
    }
    let nominal_validation_started = Instant::now();
    // Constraint checking is deferred until every aggregate definition is
    // registered, allowing structural symbolic reasoning across declaration
    // order without template-style instantiation semantics.
    for info in &structs {
        for field in &info.fields {
            validate_type_constraints(&types, field.ty, &structs, &enums, field.span).map_err(
                |diagnostics| {
                    diagnostics
                        .into_iter()
                        .map(|diagnostic| src(diagnostic, &program.modules[info.module.0 as usize]))
                        .collect::<Vec<_>>()
                },
            )?;
        }
    }
    for info in &enums {
        for payload in info.variants.iter().flat_map(|variant| &variant.payloads) {
            validate_type_constraints(&types, payload.ty, &structs, &enums, payload.span).map_err(
                |diagnostics| {
                    diagnostics
                        .into_iter()
                        .map(|diagnostic| src(diagnostic, &program.modules[info.module.0 as usize]))
                        .collect::<Vec<_>>()
                },
            )?;
        }
    }
    for alias in &alias_info {
        validate_type_constraints(&types, alias.canonical, &structs, &enums, alias.span).map_err(
            |diagnostics| {
                diagnostics
                    .into_iter()
                    .map(|diagnostic| src(diagnostic, &program.modules[alias.module.0 as usize]))
                    .collect::<Vec<_>>()
            },
        )?;
    }
    if let Some((container, element, kind)) = types.entries().find_map(|(container, data)| {
        let (element, kind) = match data {
            TypeData::Buffer { element } | TypeData::View { element, .. } => (*element, 0_u8),
            TypeData::Vector { element, .. } => (*element, 3),
            TypeData::Matrix { element } => (*element, 4),
            TypeData::Array { element } => (*element, 1),
            TypeData::List { element } => (*element, 2),
            _ => return None,
        };
        let admitted = match kind {
            1 => types.is_admitted_array_element(element),
            2 => types.is_admitted_list_element(element),
            3 => types.is_admitted_vector_element(element),
            4 => types.is_admitted_matrix_element(element),
            _ => types.is_admitted_buffer_element(element),
        };
        (!admitted).then_some((container, element, kind))
    }) {
        let location = structs
            .iter()
            .find_map(|info| {
                info.fields
                    .iter()
                    .find(|field| field.ty == container)
                    .map(|field| (field.span, info.module))
            })
            .or_else(|| {
                enums.iter().find_map(|info| {
                    info.variants
                        .iter()
                        .flat_map(|variant| &variant.payloads)
                        .find(|payload| payload.ty == container)
                        .map(|payload| (payload.span, info.module))
                })
            });
        let diagnostic = Diagnostic::new(
            match kind {
                1 => "E0304",
                2 => "E0310",
                3 => "E0325",
                4 => "E0331",
                _ => "E0280",
            },
            Phase::Semantic,
            DiagnosticCategory::Type,
            if kind == 0 {
                format!(
                    "{} cannot use a non-Copy/drop-requiring, borrowed, or owning element type {}",
                    format_type(&types, container, &structs, &enums),
                    format_type(&types, element, &structs, &enums)
                )
            } else {
                collection_admission_message(
                    if kind == 4 {
                        "Matrix"
                    } else if kind == 1 {
                        "Array"
                    } else if kind == 3 {
                        "Vector"
                    } else {
                        "List"
                    },
                    format_type(&types, element, &structs, &enums),
                    types.collection_element_admission(
                        if kind == 4 {
                            CollectionKind::Matrix
                        } else if kind == 3 {
                            CollectionKind::Vector
                        } else if kind == 1 {
                            CollectionKind::Array
                        } else {
                            CollectionKind::List
                        },
                        element,
                    ),
                )
            },
            location.map(|(span, _)| span),
        );
        let diagnostic = if let Some((_, module)) = location {
            src(diagnostic, &program.modules[module.0 as usize])
        } else {
            diagnostic
        };
        return Err(vec![diagnostic]);
    }
    for info in &structs {
        if let Some(field) = info.fields.iter().find(|field| {
            types.contains_class(field.ty)
                || types.contains_reference(field.ty)
                || types.contains_view(field.ty)
        }) {
            return Err(vec![src(
                Diagnostic::new(
                    "E0274",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "references and views cannot be stored transitively in struct fields",
                    Some(field.span),
                ),
                &program.modules[info.module.0 as usize],
            )]);
        }
    }
    for info in &enums {
        if let Some(payload) = info
            .variants
            .iter()
            .flat_map(|variant| &variant.payloads)
            .find(|payload| {
                types.contains_class(payload.ty)
                    || types.contains_reference(payload.ty)
                    || types.contains_view(payload.ty)
            })
        {
            return Err(vec![src(
                Diagnostic::new(
                    "E0275",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "references and views cannot be stored transitively in enum payloads",
                    Some(payload.span),
                ),
                &program.modules[info.module.0 as usize],
            )]);
        }
    }
    types.record_semantic_time(
        "frontend.detail.nominal_second_pass",
        nominal_validation_started,
    );
    let mut signatures = vec![];
    let mut names = vec![BTreeMap::new(); program.modules.len()];
    for module in &program.modules {
        for f in module.ast.functions() {
            let id = FunctionId(signatures.len() as u32);
            names[module.info.id.0 as usize].insert(f.name.clone(), id);
            if types.class_method(id).is_some()
                && let Some(parameter) = f.parameters.iter().find(|p| p.default.is_some())
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0367",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        "default parameters are not yet supported on methods or initializers",
                        parameter.default_equals_span.or(Some(parameter.span)),
                    ),
                    module,
                )]);
            }
            if let Some(first_default) = f.parameters.iter().position(|p| p.default.is_some())
                && let Some(required) = f.parameters[first_default + 1..]
                    .iter()
                    .find(|p| p.default.is_none())
            {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0360",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "parameter `{}` is required after a parameter with a default",
                            required.name
                        ),
                        Some(required.span),
                    ),
                    module,
                )]);
            }
            let generic_parameters = collect_generic_parameters(
                GenericOwner::Function(id.0),
                &f.generic_parameters,
                &mut types,
            )
            .map_err(|diagnostic| vec![src(diagnostic, module)])?;
            let generic_scope = generic_parameters
                .iter()
                .map(|parameter| (parameter.name.clone(), parameter.ty))
                .collect::<BTreeMap<_, _>>();
            let mut parameters = f
                .parameters
                .iter()
                .enumerate()
                .map(|(index, p)| {
                    resolve_type_in_module(
                        &p.ty,
                        module.info.id,
                        &aliases,
                        &struct_names,
                        &enum_names,
                        &imports,
                        &module_names,
                        &mut types,
                        &generic_scope,
                        &struct_arities,
                        &enum_arities,
                    )
                    .map(|ty| ParameterSignature {
                        name: p.name.clone(),
                        ty,
                        mutability: p.mutability,
                        default: p.default.clone().map(|expression| DefaultArgumentTemplate {
                            parameter_index: u32::try_from(index)
                                .expect("parameter index fits u32"),
                            expression,
                            equals_span: p.default_equals_span.expect("default has equals span"),
                        }),
                        span: p.span,
                    })
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|d| vec![src(d, module)])?;
            if let Some((class, method)) = types.class_method(id) {
                let kind = ClassTokenKind::Receiver {
                    mutable: method.mutable,
                    initializing: method.initializing,
                };
                parameters[0].ty = types.intern(TypeData::ClassToken { class, kind });
            }
            let return_type = resolve_type_in_module(
                &f.return_type,
                module.info.id,
                &aliases,
                &struct_names,
                &enum_names,
                &imports,
                &module_names,
                &mut types,
                &generic_scope,
                &struct_arities,
                &enum_arities,
            )
            .map_err(|d| vec![src(d, module)])?;
            if types.contains_function(return_type) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0357",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        "returning Function values is not supported in FUNCTION-VALUES-V1",
                        Some(f.return_type.span),
                    ),
                    module,
                )]);
            }
            for parameter in &parameters {
                if parameter.ty == TypeId::VOID {
                    return Err(vec![src(
                        type_error("void is not a valid parameter type", parameter.span),
                        module,
                    )]);
                }
                validate_type_constraints(&types, parameter.ty, &structs, &enums, parameter.span)
                    .map_err(|diagnostics| {
                    diagnostics
                        .into_iter()
                        .map(|diagnostic| src(diagnostic, module))
                        .collect::<Vec<_>>()
                })?;
            }
            validate_type_constraints(&types, return_type, &structs, &enums, f.return_type.span)
                .map_err(|diagnostics| {
                    diagnostics
                        .into_iter()
                        .map(|diagnostic| src(diagnostic, module))
                        .collect::<Vec<_>>()
                })?;
            if types.contains_reference(return_type) || types.contains_view(return_type) {
                return Err(vec![src(
                    Diagnostic::new(
                        "E0273",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "non-owning references/views cannot escape through a function return type in Vertical-10",
                        Some(f.return_type.span),
                    ),
                    module,
                )]);
            }
            signatures.push(FunctionSignature {
                id,
                module: module.info.id,
                name: f.name.clone(),
                generic_parameters,
                parameters,
                return_type,
                span: f.span,
            });
        }
    }
    merge_package_tables(&program, &mut names);
    for c in &mut types.classes {
        for m in &mut c.methods {
            let s = &signatures[m.function.0 as usize];
            m.parameters = s.parameters[1..].iter().map(|p| p.ty).collect();
            m.result = s.return_type;
        }
    }
    // Resolve interface contracts and explicit nominal relations.
    for module in &program.modules {
        for source in module.ast.interfaces() {
            let iid = types
                .interfaces
                .iter()
                .find(|i| i.module == module.info.id && i.name == source.name)
                .unwrap()
                .id;
            let mut requirements = Vec::new();
            for (index, r) in source.requirements.iter().enumerate() {
                if let Some(parameter) = r.parameters.iter().find(|p| p.default.is_some()) {
                    return Err(vec![src(
                        Diagnostic::new(
                            "E0367",
                            Phase::Semantic,
                            DiagnosticCategory::Unsupported,
                            "default parameters are not yet supported on interface requirements",
                            parameter.default_equals_span.or(Some(parameter.span)),
                        ),
                        module,
                    )]);
                }
                let mut resolve = |ty: &AstType| {
                    resolve_type_in_module(
                        ty,
                        module.info.id,
                        &aliases,
                        &struct_names,
                        &enum_names,
                        &imports,
                        &module_names,
                        &mut types,
                        &BTreeMap::new(),
                        &struct_arities,
                        &enum_arities,
                    )
                    .map_err(|d| vec![src(d, module)])
                };
                let parameters = r
                    .parameters
                    .iter()
                    .map(|p| resolve(&p.ty))
                    .collect::<Result<Vec<_>, _>>()?;
                let result = resolve(&r.result)?;
                for ty in parameters.iter().chain(std::iter::once(&result)) {
                    validate_type_constraints(&types, *ty, &structs, &enums, r.span)
                        .map_err(|ds| ds.into_iter().map(|d| src(d, module)).collect::<Vec<_>>())?;
                }
                requirements.push(crate::RequirementInfo {
                    id: crate::RequirementId {
                        interface: iid,
                        index: index as u32,
                    },
                    name: r.name.clone(),
                    mutable: r.mutable,
                    parameters,
                    result,
                    span: r.span,
                });
            }
            types.interfaces[iid.0 as usize].requirements = requirements;
        }
    }
    for module in &program.modules {
        for source in module.ast.classes() {
            let cid = types
                .classes
                .iter()
                .find(|c| c.module == module.info.id && c.name == source.name)
                .unwrap()
                .id;
            for relation in &source.relations {
                let ty = resolve_type_in_module(
                    relation,
                    module.info.id,
                    &aliases,
                    &struct_names,
                    &enum_names,
                    &imports,
                    &module_names,
                    &mut types,
                    &BTreeMap::new(),
                    &struct_arities,
                    &enum_arities,
                )
                .map_err(|d| vec![src(d, module)])?;
                if let Some(base) = types.class_id(ty) {
                    if types.classes[cid.0 as usize].base.replace(base).is_some() {
                        return Err(vec![classes::error(
                            "E0420",
                            "at most one class base is permitted",
                            relation.span,
                        )]);
                    }
                    continue;
                }
                let iid = types.interface_id(ty).ok_or_else(|| {
                    vec![classes::error(
                        "E0411",
                        "class relation requires a class or interface",
                        relation.span,
                    )]
                })?;
                if types.classes[cid.0 as usize].interfaces.contains(&iid) {
                    return Err(vec![src(
                        classes::error(
                            "E0412",
                            "duplicate canonical interface conformance",
                            relation.span,
                        ),
                        module,
                    )]);
                }
                if source.public && !types.interfaces[iid.0 as usize].public {
                    return Err(vec![src(
                        classes::error(
                            "E0412",
                            "public class conformance exposes internal interface",
                            relation.span,
                        ),
                        module,
                    )]);
                }
                types.classes[cid.0 as usize].interfaces.push(iid);
            }
        }
    }
    classes::resolve_inheritance(&mut types)?;
    crate::verify_interface_metadata(&types).map_err(|m| {
        vec![classes::error(
            "E0412",
            m,
            program.modules[0]
                .ast
                .interfaces()
                .first()
                .map_or(Span::new(0, 0), |i| i.span),
        )]
    })?;
    // Resolve class fields after the existing aggregate declarations.
    for module in &program.modules {
        for class in module.ast.classes() {
            let cid = types
                .classes
                .iter()
                .find(|c| c.module == module.info.id && c.name == class.name)
                .unwrap()
                .id;
            for (public, field) in &class.fields {
                let ty = resolve_type_in_module(
                    &field.ty,
                    module.info.id,
                    &aliases,
                    &struct_names,
                    &enum_names,
                    &imports,
                    &module_names,
                    &mut types,
                    &BTreeMap::new(),
                    &struct_arities,
                    &enum_arities,
                )
                .map_err(|d| vec![src(d, module)])?;
                if types.contains_function(ty) {
                    return Err(vec![classes::error(
                        "E0357",
                        "Function fields are not supported in FUNCTION-VALUES-V1",
                        field.span,
                    )]);
                }
                let narrow_buffer = types.buffer_element(ty) == Some(TypeId::INT64) && !public;
                let narrow_class_owner =
                    types.class_id(ty).is_some_and(|owner| owner != cid) && !public;
                if !narrow_buffer
                    && !narrow_class_owner
                    && (!types.guarantees_copy(ty)
                        || types.contains_owning(ty)
                        || types.contains_reference(ty)
                        || types.contains_view(ty)
                        || types.contains_generic(ty))
                {
                    return Err(vec![classes::error(
                        "E0401",
                        "class field requires a scalar/Copy value, private Buffer<int>, or a private non-self concrete class owner",
                        field.span,
                    )]);
                }
                let fields = &mut types.classes[cid.0 as usize].fields;
                if fields.iter().any(|f| f.name == field.name) {
                    return Err(vec![duplicate("class field", &field.name, field.span)]);
                }
                fields.push(crate::ClassFieldInfo {
                    id: FieldId(next_field),
                    class: cid,
                    name: field.name.clone(),
                    ty,
                    public: *public,
                    index: fields.len() as u32,
                    offset: 0,
                    span: field.span,
                });
                next_field += 1;
            }
        }
    }
    let em = &program.modules[program.entry.0 as usize];
    let Some(entry) = names[program.entry.0 as usize].get("main").copied() else {
        return Err(vec![src(
            Diagnostic::new(
                "E0200",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "entry module requires `int main()`",
                em.ast.functions().first().map(|f| f.span),
            ),
            em,
        )]);
    };
    let main = &signatures[entry.0 as usize];
    if main.return_type != TypeId::INT64
        || !main.parameters.is_empty()
        || !main.generic_parameters.is_empty()
    {
        return Err(vec![src(
            Diagnostic::new(
                "E0201",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "entry function must have signature `int main()`",
                Some(main.span),
            ),
            em,
        )]);
    }
    Ok(DeclaredProgram {
        types,
        program,
        signatures,
        names,
        imports,
        import_bindings,
        module_names,
        aliases,
        alias_info,
        structs,
        enums,
        struct_names,
        enum_names,
        variant_names,
        field_names,
        struct_arities,
        enum_arities,
        entry,
    })
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum AliasState {
    Visiting,
    Done,
}
#[allow(clippy::too_many_arguments)]
fn resolve_alias(
    name: &str,
    module: &ParsedModule,
    decl: &BTreeMap<String, &crate::AstAlias>,
    struct_names: &[BTreeMap<String, StructId>],
    enum_names: &[BTreeMap<String, EnumId>],
    imports: &[BTreeMap<String, ModuleId>],
    module_names: &BTreeMap<String, ModuleId>,
    types: &mut TypeArena,
    struct_arities: &[usize],
    enum_arities: &[usize],
    state: &mut BTreeMap<String, AliasState>,
    resolved: &mut BTreeMap<String, TypeId>,
    info: &mut Vec<TypeAliasInfo>,
) -> Result<TypeId, Vec<Diagnostic>> {
    if let Some(t) = resolved.get(name) {
        return Ok(*t);
    }
    if state.get(name) == Some(&AliasState::Visiting) {
        let a = decl[name];
        return Err(vec![src(
            Diagnostic::new(
                "E0226",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("type alias cycle contains `{name}`"),
                Some(a.span),
            ),
            module,
        )]);
    }
    state.insert(name.into(), AliasState::Visiting);
    let a = decl[name];
    let alias_target = a.target.named();
    let ty = if let Some((None, target_name, [])) = alias_target
        && decl.contains_key(target_name)
    {
        resolve_alias(
            target_name,
            module,
            decl,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            struct_arities,
            enum_arities,
            state,
            resolved,
            info,
        )?
    } else {
        let alias_snapshot = vec![BTreeMap::new(); struct_names.len()];
        resolve_type_in_module(
            &a.target,
            module.info.id,
            &alias_snapshot,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            &BTreeMap::new(),
            struct_arities,
            enum_arities,
        )
        .map_err(|d| vec![src(d, module)])?
    };
    state.insert(name.into(), AliasState::Done);
    resolved.insert(name.into(), ty);
    info.push(TypeAliasInfo {
        module: module.info.id,
        name: name.into(),
        target_spelling: alias_target
            .map_or_else(|| "<structural>".into(), |(_, name, _)| name.into()),
        canonical: ty,
        span: a.span,
    });
    Ok(ty)
}

fn resolve_type_in_module(
    ty: &AstType,
    current: ModuleId,
    aliases: &[BTreeMap<String, TypeId>],
    struct_names: &[BTreeMap<String, StructId>],
    enum_names: &[BTreeMap<String, EnumId>],
    imports: &[BTreeMap<String, ModuleId>],
    module_names: &BTreeMap<String, ModuleId>,
    types: &mut TypeArena,
    generic_scope: &BTreeMap<String, TypeId>,
    struct_arities: &[usize],
    enum_arities: &[usize],
) -> Result<TypeId, Diagnostic> {
    if let crate::AstTypeKind::Nullable { payload, .. } = &ty.kind {
        let payload = resolve_type_in_module(
            payload,
            current,
            aliases,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            generic_scope,
            struct_arities,
            enum_arities,
        )?;
        return types.intern_nullable(payload).map_err(|message| {
            Diagnostic::new(
                "E0450",
                Phase::Semantic,
                DiagnosticCategory::Type,
                message,
                Some(ty.span),
            )
        });
    }
    if let crate::AstTypeKind::Reference(reference) = &ty.kind {
        let pointee = resolve_type_in_module(
            &reference.pointee,
            current,
            aliases,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            generic_scope,
            struct_arities,
            enum_arities,
        )?;
        if types.contains_class(pointee) {
            return Err(classes::error(
                "E0406",
                "class handle slot references require separate qualification",
                ty.span,
            ));
        }
        return Ok(types.intern_reference(pointee, reference.mutable));
    }
    if let crate::AstTypeKind::Function { parameters, result } = &ty.kind {
        let mut resolved = Vec::with_capacity(parameters.len());
        for parameter in parameters {
            let parameter = resolve_type_in_module(
                parameter,
                current,
                aliases,
                struct_names,
                enum_names,
                imports,
                module_names,
                types,
                generic_scope,
                struct_arities,
                enum_arities,
            )?;
            if parameter == TypeId::VOID {
                return Err(Diagnostic::new(
                    "E0350",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "Function parameter type cannot be void",
                    Some(ty.span),
                ));
            }
            resolved.push(parameter);
        }
        let result = resolve_type_in_module(
            result,
            current,
            aliases,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            generic_scope,
            struct_arities,
            enum_arities,
        )?;
        return types.intern_function(resolved, result).map_err(|message| {
            Diagnostic::new(
                "E0350",
                Phase::Semantic,
                DiagnosticCategory::Type,
                message,
                Some(ty.span),
            )
        });
    }
    let crate::AstTypeKind::Named {
        module,
        name,
        arguments: type_arguments,
    } = &ty.kind
    else {
        unreachable!("structural type handled above")
    };
    let target = if let Some(module) = module {
        let Some(target) = imports[current.0 as usize].get(module).copied() else {
            let known = module_names.contains_key(module);
            return Err(Diagnostic::new(
                if known { "E0223" } else { "E0221" },
                Phase::Semantic,
                DiagnosticCategory::Name,
                if known {
                    format!("package `{module}` is not imported")
                } else {
                    format!("unknown package path or namespace alias `{module}`")
                },
                Some(ty.span),
            ));
        };
        target
    } else {
        current
    };
    if module.is_none()
        && let Some(parameter) = generic_scope.get(name).copied()
    {
        if !type_arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(parameter);
    }
    if module.is_none()
        && matches!(name.as_str(), "Matrix" | "MatrixView" | "MatrixViewMut")
        && type_arguments.len() != 1
    {
        return Err(generic_arity(ty, 1));
    }
    if module.is_none() && matches!(name.as_str(), "Vector" | "VectorView" | "VectorViewMut") {
        if type_arguments.len() != 2 {
            return Err(generic_arity(ty, 2));
        }
        let marker = &type_arguments[1];
        let orientation = match marker.named() {
            Some((None, "Row", [])) => Orientation::Row,
            Some((None, "Column", [])) => Orientation::Column,
            _ => {
                return Err(Diagnostic::new(
                    "E0324",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "Vector orientation must be the intrinsic marker Row or Column",
                    Some(marker.span),
                ));
            }
        };
        let element = resolve_type_in_module(
            &type_arguments[0],
            current,
            aliases,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            generic_scope,
            struct_arities,
            enum_arities,
        )?;
        if name != "Vector" {
            return Ok(types.intern_vector_view(element, orientation, name == "VectorViewMut"));
        }
        let deferred_aggregate = types.properties(element).is_some_and(|p| !p.is_known)
            && (types.struct_id(element).is_some() || types.enum_id(element).is_some());
        if !types.is_admitted_vector_element(element) && !deferred_aggregate {
            return Err(Diagnostic::new(
                "E0325",
                Phase::Semantic,
                DiagnosticCategory::Type,
                collection_admission_message(
                    "Vector",
                    format_type(types, element, &[], &[]),
                    types.collection_element_admission(CollectionKind::Vector, element),
                ),
                Some(ty.span),
            ));
        }
        return Ok(types.intern_vector(element, orientation));
    }
    let mut arguments = Vec::with_capacity(type_arguments.len());
    for argument in type_arguments {
        arguments.push(resolve_type_in_module(
            argument,
            current,
            aliases,
            struct_names,
            enum_names,
            imports,
            module_names,
            types,
            generic_scope,
            struct_arities,
            enum_arities,
        )?);
    }
    if module.is_none()
        && let Some(expected) = intrinsic_type_arity(name)
    {
        if arguments.len() != expected {
            return Err(generic_arity(ty, expected));
        }
        let element = arguments[0];
        if matches!(name.as_str(), "Array" | "List") && types.contains_function(element) {
            return Err(Diagnostic::new(
                "E0357",
                Phase::Semantic,
                DiagnosticCategory::Unsupported,
                format!("{name}<Function<...>> is not supported in FUNCTION-VALUES-V1"),
                Some(ty.span),
            ));
        }
        if types.contains_generic(element)
            && !matches!(
                name.as_str(),
                "Matrix" | "MatrixView" | "MatrixViewMut" | "Array" | "List"
            )
        {
            return Err(Diagnostic::new(
                "E0283",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "{name} element types must be concrete; generic Buffer/View construction is deferred"
                ),
                Some(ty.span),
            ));
        }
        return match name.as_str() {
            "Buffer" => {
                let deferred_aggregate = types
                    .properties(element)
                    .is_some_and(|properties| !properties.is_known)
                    && (types.struct_id(element).is_some() || types.enum_id(element).is_some());
                if types.is_admitted_buffer_element(element) || deferred_aggregate {
                    Ok(types.intern_buffer(element))
                } else {
                    Err(Diagnostic::new(
                        "E0280",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "Vertical-10 Buffer elements must be concrete Copy/no-drop values without borrowed or owning substructure",
                        Some(ty.span),
                    ))
                }
            }
            "Matrix" => {
                let deferred_aggregate = types
                    .properties(element)
                    .is_some_and(|properties| !properties.is_known)
                    && (types.struct_id(element).is_some() || types.enum_id(element).is_some());
                if types.is_admitted_matrix_element(element) || deferred_aggregate {
                    Ok(types.intern_matrix(element))
                } else {
                    Err(Diagnostic::new(
                        "E0331",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        collection_admission_message(
                            "Matrix",
                            format_type(types, element, &[], &[]),
                            types.collection_element_admission(CollectionKind::Matrix, element),
                        ),
                        Some(ty.span),
                    ))
                }
            }
            "Array" => {
                let deferred_aggregate = types
                    .properties(element)
                    .is_some_and(|properties| !properties.is_known)
                    && (types.struct_id(element).is_some() || types.enum_id(element).is_some());
                if types.is_admitted_array_element(element) || deferred_aggregate {
                    Ok(types.intern_array(element))
                } else {
                    Err(Diagnostic::new(
                        "E0304",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        collection_admission_message(
                            "Array",
                            format_type(types, element, &[], &[]),
                            types.collection_element_admission(CollectionKind::Array, element),
                        ),
                        Some(ty.span),
                    ))
                }
            }
            "List" => {
                let deferred_aggregate = types
                    .properties(element)
                    .is_some_and(|properties| !properties.is_known)
                    && (types.struct_id(element).is_some() || types.enum_id(element).is_some());
                if types.is_admitted_list_element(element) || deferred_aggregate {
                    Ok(types.intern_list(element))
                } else {
                    Err(Diagnostic::new(
                        "E0310",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        collection_admission_message(
                            "List",
                            format_type(types, element, &[], &[]),
                            types.collection_element_admission(CollectionKind::List, element),
                        ),
                        Some(ty.span),
                    ))
                }
            }
            "View" | "ViewMut"
                if !types.is_admitted_buffer_element(element)
                    && !(types
                        .properties(element)
                        .is_some_and(|properties| !properties.is_known)
                        && (types.struct_id(element).is_some()
                            || types.enum_id(element).is_some())) =>
            {
                Err(Diagnostic::new(
                    "E0280",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "Vertical-10 view elements must be concrete Copy/no-drop values without borrowed or owning substructure",
                    Some(ty.span),
                ))
            }
            "MatrixView" => Ok(types.intern_matrix_view(element, false)),
            "MatrixViewMut" => Ok(types.intern_matrix_view(element, true)),
            "View" => Ok(types.intern_view(element, false)),
            "ViewMut" => Ok(types.intern_view(element, true)),
            _ => unreachable!(),
        };
    }
    if let Some(i) = types
        .interfaces
        .iter()
        .find(|i| i.module == target && i.name == *name)
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        if target != current && !i.public {
            return Err(classes::error(
                "E0412",
                "interface is internal to its module",
                ty.span,
            ));
        }
        return Ok(types.id_of(TypeData::Interface(i.id)).unwrap());
    }
    if let Some(class) = types
        .classes
        .iter()
        .find(|c| c.module == target && c.name == *name)
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        if target != current && !class.public {
            return Err(classes::error(
                "E0402",
                "class is internal to its module",
                ty.span,
            ));
        }
        return Ok(types.id_of(TypeData::Class(class.id)).unwrap());
    }
    if module.is_none()
        && name == "Exception"
        && let Some(class) = types.exception_class()
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(types.id_of(TypeData::Class(class)).unwrap());
    }
    if let Some(id) = struct_names[target.0 as usize].get(name).copied() {
        let expected = struct_arities[id.0 as usize];
        if arguments.len() != expected {
            return Err(generic_arity(ty, expected));
        }
        return if expected == 0 {
            Ok(types
                .id_of(TypeData::Struct(id))
                .expect("collected struct type"))
        } else {
            Ok(types.intern_struct_instance(id, arguments))
        };
    }
    if let Some(id) = enum_names[target.0 as usize].get(name).copied() {
        let expected = enum_arities[id.0 as usize];
        if arguments.len() != expected {
            return Err(generic_arity(ty, expected));
        }
        return if expected == 0 {
            Ok(types
                .id_of(TypeData::Enum(id))
                .expect("collected enum type"))
        } else {
            Ok(types.intern_enum_instance(id, arguments))
        };
    }
    if let Some(alias) = aliases
        .get(target.0 as usize)
        .and_then(|map| map.get(name))
        .copied()
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(alias);
    }
    if module.is_none()
        && let Some(builtin) = builtin(name)
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(builtin);
    }
    Err(unknown_type(ty))
}

fn generic_arity(ty: &AstType, expected: usize) -> Diagnostic {
    let (_, name, arguments) = ty.named().expect("generic arity applies to named type");
    Diagnostic::new(
        "E0261",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!(
            "type `{}` expects {expected} generic arguments, found {}",
            name,
            arguments.len()
        ),
        Some(ty.span),
    )
}

fn intrinsic_type_arity(name: &str) -> Option<usize> {
    if matches!(name, "Vector" | "VectorView" | "VectorViewMut") {
        return Some(2);
    }
    matches!(
        name,
        "MatrixView"
            | "MatrixViewMut"
            | "Matrix"
            | "Buffer"
            | "Array"
            | "List"
            | "View"
            | "ViewMut"
    )
    .then_some(1)
}

fn restricted_generic_argument(span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0276",
        Phase::Semantic,
        DiagnosticCategory::Type,
        "references and views cannot be used as generic type arguments",
        Some(span),
    )
}

fn collect_generic_parameters(
    owner: GenericOwner,
    parameters: &[crate::AstGenericParam],
    types: &mut TypeArena,
) -> Result<Vec<GenericParamInfo>, Diagnostic> {
    let started = Instant::now();
    let mut seen = BTreeSet::new();
    let result = parameters
        .iter()
        .enumerate()
        .map(|(index, parameter)| {
            if !seen.insert(parameter.name.clone()) {
                return Err(Diagnostic::new(
                    "E0260",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("duplicate generic parameter `{}`", parameter.name),
                    Some(parameter.span),
                ));
            }
            let id = GenericParamId {
                owner,
                index: index as u32,
            };
            let mut capabilities = BTreeSet::new();
            for constraint in &parameter.constraints {
                let capability = match constraint.name.as_str() {
                    "Copy" => Capability::Copy,
                    "Relocatable" => Capability::Relocatable,
                    "Storable" => Capability::Storable,
                    "Add" => Capability::Behavioral(BehavioralCapability::Add),
                    "Sub" => Capability::Behavioral(BehavioralCapability::Sub),
                    "Mul" => Capability::Behavioral(BehavioralCapability::Mul),
                    "Zero" => Capability::Algebraic(AlgebraicCapability::Zero),
                    _ => {
                        return Err(Diagnostic::new(
                            "E0314",
                            Phase::Semantic,
                            DiagnosticCategory::Name,
                            format!("unknown generic capability `{}`", constraint.name),
                            Some(constraint.span),
                        ));
                    }
                };
                if !capabilities.insert(capability) {
                    return Err(Diagnostic::new(
                        "E0315",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "duplicate `{capability}` constraint on generic parameter `{}`",
                            parameter.name
                        ),
                        Some(constraint.span),
                    ));
                }
            }
            types.register_generic_capabilities(
                id,
                parameter.name.clone(),
                capabilities.iter().copied(),
            );
            Ok(GenericParamInfo {
                id,
                name: parameter.name.clone(),
                ty: types.intern(TypeData::GenericParam(id)),
                capabilities,
                span: parameter.span,
            })
        })
        .collect();
    types.record_semantic_time("frontend.detail.constraint_resolution", started);
    result
}

fn generic_call_arity(name: &str, expected: usize, found: usize, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0262",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!("generic declaration `{name}` expects {expected} type arguments, found {found}"),
        Some(span),
    )
}

fn validate_generic_constraints(
    types: &TypeArena,
    parameters: &[GenericParamInfo],
    arguments: &[TypeId],
    declaration_name: &str,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    span: Span,
    inferred: bool,
) -> Result<(), Vec<Diagnostic>> {
    if arguments.iter().any(|ty| types.contains_class(*ty)) {
        return Err(vec![classes::error(
            "E0409",
            "class-containing generic applications require separate Alias qualification",
            span,
        )]);
    }

    for (parameter, argument) in parameters.iter().zip(arguments) {
        for capability in &parameter.capabilities {
            if !types.guarantees_capability(*argument, *capability) {
                let actual = format_type(types, *argument, structs, enums);
                let symbolic = types.contains_generic(*argument);
                let detail = if symbolic {
                    "does not provide the required guarantee"
                } else {
                    "does not satisfy"
                };
                let available = [
                    Capability::Copy,
                    Capability::Relocatable,
                    Capability::Storable,
                ]
                .into_iter()
                .chain(BehavioralCapability::ALL.map(Capability::Behavioral))
                .chain([Capability::Algebraic(AlgebraicCapability::Zero)])
                .filter(|available| types.guarantees_capability(*argument, *available))
                .map(|available| available.to_string())
                .collect::<Vec<_>>()
                .join(" + ");
                let subject = if inferred {
                    format!("inference succeeded, but inferred type `{actual}`")
                } else if symbolic {
                    format!("symbolic type `{actual}`")
                } else {
                    format!("type `{actual}`")
                };
                let guarantee_detail = if symbolic {
                    format!(
                        "; available guarantees: {}",
                        if available.is_empty() {
                            "none"
                        } else {
                            &available
                        }
                    )
                } else {
                    String::new()
                };
                return Err(vec![Diagnostic::new(
                    if inferred { "E0317" } else { "E0316" },
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "{subject} {detail} `{capability}`; required by generic parameter `{}` of `{declaration_name}`{}",
                        parameter.name, guarantee_detail
                    ),
                    Some(span),
                )]);
            }
        }
    }
    if arguments
        .iter()
        .any(|argument| types.contains_reference(*argument) || types.contains_view(*argument))
    {
        return Err(vec![restricted_generic_argument(span)]);
    }
    Ok(())
}

fn validate_type_constraints(
    types: &TypeArena,
    ty: TypeId,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    span: Span,
) -> Result<(), Vec<Diagnostic>> {
    let (parameters, arguments, name) = match types.get(ty).copied() {
        Some(TypeData::StructInstance(id, arguments)) => (
            &structs[id.0 as usize].generic_parameters,
            types.arguments(arguments).unwrap_or(&[]),
            structs[id.0 as usize].name.as_str(),
        ),
        Some(TypeData::EnumInstance(id, arguments)) => (
            &enums[id.0 as usize].generic_parameters,
            types.arguments(arguments).unwrap_or(&[]),
            enums[id.0 as usize].name.as_str(),
        ),
        Some(
            TypeData::Matrix { element }
            | TypeData::Vector { element, .. }
            | TypeData::Array { element }
            | TypeData::List { element },
        ) => {
            let (kind, name, code) = if types.matrix_like_element(ty).is_some() {
                (CollectionKind::Matrix, "Matrix", "E0331")
            } else if types.vector_element(ty).is_some() {
                (CollectionKind::Vector, "Vector", "E0325")
            } else if types.array_element(ty).is_some() {
                (CollectionKind::Array, "Array", "E0304")
            } else {
                (CollectionKind::List, "List", "E0310")
            };
            let admission = types.collection_element_admission(kind, element);
            if admission != CollectionElementAdmission::Admitted {
                return Err(vec![Diagnostic::new(
                    code,
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    collection_admission_message(
                        name,
                        format_type(types, element, structs, enums),
                        admission,
                    ),
                    Some(span),
                )]);
            }
            return validate_type_constraints(types, element, structs, enums, span);
        }
        Some(
            TypeData::Reference { pointee: ty, .. }
            | TypeData::Nullable(ty)
            | TypeData::Buffer { element: ty }
            | TypeData::View { element: ty, .. }
            | TypeData::VectorView { element: ty, .. }
            | TypeData::MatrixView { element: ty, .. },
        ) => return validate_type_constraints(types, ty, structs, enums, span),
        _ => return Ok(()),
    };
    validate_generic_constraints(
        types, parameters, arguments, name, structs, enums, span, false,
    )?;
    for argument in arguments {
        validate_type_constraints(types, *argument, structs, enums, span)?;
    }
    Ok(())
}

fn incomplete_substitution(parameter: GenericParamId, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0264",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!("incomplete substitution for {parameter:?}"),
        Some(span),
    )
}

fn infer_generic_arguments(
    types: &TypeArena,
    pattern: TypeId,
    actual: TypeId,
    inferred: &mut BTreeMap<GenericParamId, TypeId>,
) -> Result<(), Vec<Diagnostic>> {
    // BORROW-ERGONOMICS-V1 never infers through the later `T -> ref T`
    // adaptation. Another argument (or explicit application) must determine T.
    if types.reference_info(pattern).is_some() && types.reference_info(actual).is_none() {
        return Ok(());
    }
    if let Some(parameter) = types.generic_param(pattern) {
        if let Some(previous) = inferred.insert(parameter, actual)
            && previous != actual
        {
            return Err(vec![type_error(
                "conflicting inferred generic arguments",
                Span::in_source(SourceId(0), 0, 0),
            )]);
        }
        return Ok(());
    }
    if let Some(payload) = types.nullable_payload(pattern)
        && types.nullable_payload(actual).is_none()
    {
        return infer_generic_arguments(types, payload, actual, inferred);
    }
    match (types.get(pattern), types.get(actual)) {
        (
            Some(TypeData::Vector {
                element: left,
                orientation: lo,
            }),
            Some(TypeData::Vector {
                element: right,
                orientation: ro,
            }),
        ) if lo == ro => infer_generic_arguments(types, *left, *right, inferred),
        (
            Some(TypeData::VectorView {
                element: left,
                orientation: lo,
                mutable: lm,
            }),
            Some(TypeData::VectorView {
                element: right,
                orientation: ro,
                mutable: rm,
            }),
        ) if lo == ro && lm == rm => infer_generic_arguments(types, *left, *right, inferred),
        (
            Some(TypeData::MatrixView {
                element: left,
                mutable: lm,
            }),
            Some(TypeData::MatrixView {
                element: right,
                mutable: rm,
            }),
        ) if lm == rm => infer_generic_arguments(types, *left, *right, inferred),
        (Some(TypeData::Nullable(left)), Some(TypeData::Nullable(right)))
        | (Some(TypeData::Matrix { element: left }), Some(TypeData::Matrix { element: right }))
        | (Some(TypeData::Array { element: left }), Some(TypeData::Array { element: right }))
        | (Some(TypeData::List { element: left }), Some(TypeData::List { element: right })) => {
            infer_generic_arguments(types, *left, *right, inferred)
        }
        (
            Some(TypeData::Reference {
                pointee: left,
                mutable: left_mutable,
            }),
            Some(TypeData::Reference {
                pointee: right,
                mutable: right_mutable,
            }),
        ) if left_mutable == right_mutable => {
            infer_generic_arguments(types, *left, *right, inferred)
        }
        (
            Some(TypeData::StructInstance(left, left_args)),
            Some(TypeData::StructInstance(right, right_args)),
        ) if left == right => {
            for (left, right) in types
                .arguments(*left_args)
                .unwrap()
                .iter()
                .zip(types.arguments(*right_args).unwrap())
            {
                infer_generic_arguments(types, *left, *right, inferred)?;
            }
            Ok(())
        }
        (
            Some(TypeData::EnumInstance(left, left_args)),
            Some(TypeData::EnumInstance(right, right_args)),
        ) if left == right => {
            for (left, right) in types
                .arguments(*left_args)
                .unwrap()
                .iter()
                .zip(types.arguments(*right_args).unwrap())
            {
                infer_generic_arguments(types, *left, *right, inferred)?;
            }
            Ok(())
        }
        _ if pattern == actual => Ok(()),
        _ => Err(vec![type_error(
            "argument does not match generic parameter pattern",
            Span::in_source(SourceId(0), 0, 0),
        )]),
    }
}

fn align_up(value: u64, align: u64) -> u64 {
    value.div_ceil(align) * align
}

#[allow(clippy::items_after_statements)]
fn compute_aggregate_layouts(
    types: &TypeArena,
    structs: &mut [StructInfo],
    enums: &mut [EnumInfo],
    target: TargetProperties,
) -> Result<(), (TypeId, String)> {
    #[derive(Clone, Copy)]
    enum Node {
        Struct(StructId),
        Enum(EnumId),
    }
    fn node_type(node: Node, types: &TypeArena) -> TypeId {
        match node {
            Node::Struct(id) => types.id_of(TypeData::Struct(id)).expect("interned struct"),
            Node::Enum(id) => types.id_of(TypeData::Enum(id)).expect("interned enum"),
        }
    }
    fn node_index(node: Node, struct_count: usize) -> usize {
        match node {
            Node::Struct(id) => id.0 as usize,
            Node::Enum(id) => struct_count + id.0 as usize,
        }
    }
    fn visit(
        node: Node,
        structs: &[StructInfo],
        enums: &[EnumInfo],
        types: &TypeArena,
        state: &mut [u8],
    ) -> Result<(), (TypeId, String)> {
        let index = node_index(node, structs.len());
        if state[index] == 2 {
            return Ok(());
        }
        if state[index] == 1 {
            let name = match node {
                Node::Struct(id) => &structs[id.0 as usize].name,
                Node::Enum(id) => &enums[id.0 as usize].name,
            };
            let identity = enums
                .iter()
                .enumerate()
                .find(|(enum_index, _)| state[structs.len() + enum_index] == 1)
                .map_or_else(
                    || node_type(node, types),
                    |(enum_index, _)| {
                        types
                            .id_of(TypeData::Enum(EnumId(enum_index as u32)))
                            .expect("interned enum")
                    },
                );
            return Err((
                identity,
                format!("recursive by-value aggregate `{name}` has infinite size"),
            ));
        }
        state[index] = 1;
        let child_types: Vec<TypeId> = match node {
            Node::Struct(id) => structs[id.0 as usize]
                .fields
                .iter()
                .map(|field| field.ty)
                .collect(),
            Node::Enum(id) => enums[id.0 as usize]
                .variants
                .iter()
                .flat_map(|variant| variant.payloads.iter().map(|payload| payload.ty))
                .collect(),
        };
        for ty in child_types {
            let mut inline = ty;
            while let Some(TypeData::Nullable(payload)) = types.get(inline) {
                inline = *payload;
            }
            match types.get(inline) {
                Some(TypeData::Struct(id) | TypeData::StructInstance(id, _)) => {
                    visit(Node::Struct(*id), structs, enums, types, state)?
                }
                Some(TypeData::Enum(id) | TypeData::EnumInstance(id, _)) => {
                    visit(Node::Enum(*id), structs, enums, types, state)?
                }
                _ => {}
            }
        }
        state[index] = 2;
        Ok(())
    }
    let mut cycle_state = vec![0_u8; structs.len() + enums.len()];
    for index in 0..structs.len() {
        visit(
            Node::Struct(StructId(index as u32)),
            structs,
            enums,
            types,
            &mut cycle_state,
        )?;
    }
    for index in 0..enums.len() {
        visit(
            Node::Enum(EnumId(index as u32)),
            structs,
            enums,
            types,
            &mut cycle_state,
        )?;
    }

    fn type_layout(
        ty: TypeId,
        structs: &mut [StructInfo],
        enums: &mut [EnumInfo],
        types: &TypeArena,
        struct_state: &mut [u8],
        enum_state: &mut [u8],
        target: TargetProperties,
    ) -> TypeLayout {
        match types.get(ty).expect("layout requires valid TypeId") {
            TypeData::Bool => TypeLayout { size: 1, align: 1 },
            TypeData::Char | TypeData::Float(FloatType::Float32) => {
                TypeLayout { size: 4, align: 4 }
            }
            TypeData::Integer(integer) => {
                let bytes = u64::from(integer.bits(target) / 8);
                TypeLayout {
                    size: bytes,
                    align: bytes,
                }
            }
            TypeData::Float(FloatType::Float64) => TypeLayout { size: 8, align: 8 },
            TypeData::Struct(id) => {
                struct_layout(*id, structs, enums, types, struct_state, enum_state, target)
            }
            TypeData::Enum(id) => {
                enum_layout(*id, structs, enums, types, struct_state, enum_state, target)
            }
            TypeData::StructInstance(_, _) | TypeData::EnumInstance(_, _) => types
                .cached_layout(ty)
                .map_or(TypeLayout { size: 0, align: 1 }, |(size, align)| {
                    TypeLayout { size, align }
                }),
            TypeData::String
            | TypeData::Class(_)
            | TypeData::ClassToken { .. }
            | TypeData::Interface(_)
            | TypeData::InterfaceKeepalive { .. }
            | TypeData::Reference { .. }
            | TypeData::Function { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes,
                    align: bytes,
                }
            }
            TypeData::Buffer { .. }
            | TypeData::Vector { .. }
            | TypeData::Array { .. }
            | TypeData::View { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes * 2,
                    align: bytes,
                }
            }
            TypeData::MatrixView { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes * 5,
                    align: bytes,
                }
            }
            TypeData::VectorView { .. } | TypeData::Matrix { .. } | TypeData::List { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes * 3,
                    align: bytes,
                }
            }
            TypeData::Nullable(payload) => {
                let payload_layout = type_layout(
                    *payload,
                    structs,
                    enums,
                    types,
                    struct_state,
                    enum_state,
                    target,
                );
                if matches!(
                    types.get(*payload),
                    Some(
                        TypeData::String
                            | TypeData::Class(_)
                            | TypeData::Reference { .. }
                            | TypeData::Function { .. }
                    )
                ) {
                    payload_layout
                } else {
                    let offset = align_up(1, payload_layout.align);
                    TypeLayout {
                        size: align_up(offset + payload_layout.size, payload_layout.align),
                        align: payload_layout.align,
                    }
                }
            }
            TypeData::Void | TypeData::GenericParam(_) => TypeLayout { size: 0, align: 1 },
        }
    }
    fn struct_layout(
        id: StructId,
        structs: &mut [StructInfo],
        enums: &mut [EnumInfo],
        types: &TypeArena,
        struct_state: &mut [u8],
        enum_state: &mut [u8],
        target: TargetProperties,
    ) -> TypeLayout {
        if struct_state[id.0 as usize] == 2 {
            return structs[id.0 as usize].layout;
        }
        struct_state[id.0 as usize] = 1;
        let field_types: Vec<TypeId> = structs[id.0 as usize]
            .fields
            .iter()
            .map(|field| field.ty)
            .collect();
        let mut offset = 0;
        let mut aggregate_align = 1;
        let mut offsets = Vec::with_capacity(field_types.len());
        for ty in field_types {
            let layout = type_layout(ty, structs, enums, types, struct_state, enum_state, target);
            offset = align_up(offset, layout.align);
            offsets.push(offset);
            offset += layout.size;
            aggregate_align = aggregate_align.max(layout.align);
        }
        let layout = TypeLayout {
            size: align_up(offset, aggregate_align),
            align: aggregate_align,
        };
        for (field, field_offset) in structs[id.0 as usize].fields.iter_mut().zip(offsets) {
            field.offset = field_offset;
        }
        structs[id.0 as usize].layout = layout;
        struct_state[id.0 as usize] = 2;
        layout
    }
    fn enum_layout(
        id: EnumId,
        structs: &mut [StructInfo],
        enums: &mut [EnumInfo],
        types: &TypeArena,
        struct_state: &mut [u8],
        enum_state: &mut [u8],
        target: TargetProperties,
    ) -> TypeLayout {
        if enum_state[id.0 as usize] == 2 {
            return enums[id.0 as usize].layout;
        }
        enum_state[id.0 as usize] = 1;
        let variant_types: Vec<Vec<TypeId>> = enums[id.0 as usize]
            .variants
            .iter()
            .map(|variant| variant.payloads.iter().map(|payload| payload.ty).collect())
            .collect();
        let mut offset = 4_u64;
        let mut aggregate_align = 4_u64;
        let mut computed = Vec::new();
        for payload_types in variant_types {
            let mut tuple_offset = 0_u64;
            let mut tuple_align = 1_u64;
            let mut payload_offsets = Vec::new();
            for ty in payload_types {
                let layout =
                    type_layout(ty, structs, enums, types, struct_state, enum_state, target);
                tuple_offset = align_up(tuple_offset, layout.align);
                payload_offsets.push(tuple_offset);
                tuple_offset += layout.size;
                tuple_align = tuple_align.max(layout.align);
            }
            let storage_layout = TypeLayout {
                size: align_up(tuple_offset, tuple_align),
                align: tuple_align,
            };
            offset = align_up(offset, tuple_align);
            let storage_offset = offset;
            offset += storage_layout.size;
            aggregate_align = aggregate_align.max(tuple_align);
            computed.push((storage_offset, storage_layout, payload_offsets));
        }
        let layout = TypeLayout {
            size: align_up(offset, aggregate_align),
            align: aggregate_align,
        };
        for (variant, (storage_offset, storage_layout, payload_offsets)) in
            enums[id.0 as usize].variants.iter_mut().zip(computed)
        {
            variant.storage_offset = storage_offset;
            variant.storage_layout = storage_layout;
            for (payload, relative) in variant.payloads.iter_mut().zip(payload_offsets) {
                payload.offset = storage_offset + relative;
            }
        }
        enums[id.0 as usize].layout = layout;
        enum_state[id.0 as usize] = 2;
        layout
    }

    let mut struct_state = vec![0_u8; structs.len()];
    let mut enum_state = vec![0_u8; enums.len()];
    for index in 0..structs.len() {
        struct_layout(
            StructId(index as u32),
            structs,
            enums,
            types,
            &mut struct_state,
            &mut enum_state,
            target,
        );
    }
    for index in 0..enums.len() {
        enum_layout(
            EnumId(index as u32),
            structs,
            enums,
            types,
            &mut struct_state,
            &mut enum_state,
            target,
        );
    }
    Ok(())
}

fn src(d: Diagnostic, m: &ParsedModule) -> Diagnostic {
    d.with_source_name(&m.info.source_name)
}

pub fn analyze_bodies(d: DeclaredProgram) -> Result<TypedHir, Vec<Diagnostic>> {
    analyze_bodies_for_target(d, TargetProperties::LINUX_X86_64)
}
pub fn analyze_bodies_for_target(
    mut d: DeclaredProgram,
    target: TargetProperties,
) -> Result<TypedHir, Vec<Diagnostic>> {
    compute_aggregate_layouts(&d.types, &mut d.structs, &mut d.enums, target).map_err(
        |(ty, message)| {
            let (span, module) = match d.types.get(ty) {
                Some(TypeData::Struct(id)) => (
                    d.structs[id.0 as usize].span,
                    d.structs[id.0 as usize].module,
                ),
                Some(TypeData::Enum(id)) => {
                    (d.enums[id.0 as usize].span, d.enums[id.0 as usize].module)
                }
                _ => unreachable!(),
            };
            let code = if d.types.struct_id(ty).is_some() {
                "E0242"
            } else {
                "E0259"
            };
            vec![
                Diagnostic::new(
                    code,
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    message,
                    Some(span),
                )
                .with_source_name(&d.program.modules[module.0 as usize].info.source_name),
            ]
        },
    )?;
    let mut functions = vec![];
    let mut semantic_dependencies = vec![BTreeSet::new(); d.program.modules.len()];
    let mut types = std::mem::take(&mut d.types);
    classes::compute_layouts(&mut types, &d.structs, &d.enums, target)?;
    for m in &d.program.modules {
        for f in m.ast.functions() {
            let id = FunctionId(functions.len() as u32);
            let (function, dependencies) =
                analyze_function(f, id, m.info.id, &d, &mut types, target).map_err(|ds| {
                    ds.into_iter()
                        .map(|x| x.with_source_name(&m.info.source_name))
                        .collect::<Vec<_>>()
                })?;
            semantic_dependencies[m.info.id.0 as usize].extend(dependencies);
            functions.push(function);
        }
    }
    let generic_functions = functions;
    verify_parametric_hir(
        &generic_functions,
        &d.signatures,
        &d.structs,
        &d.enums,
        &types,
    )?;
    let (instances, functions, entry) = monomorphize(
        &mut types,
        &d.signatures,
        &generic_functions,
        &d.structs,
        &d.enums,
        d.entry,
    )?;
    compute_concrete_layouts(&mut types, &d.structs, &d.enums, target)?;
    let hir = TypedHir {
        modules: d
            .program
            .modules
            .iter()
            .map(|m| {
                let mut info = m.info.clone();
                // Imports are source-unit lookup grants. Once bodies have been
                // resolved, downstream IR retains only canonical dependencies.
                info.imports.clear();
                info.semantic_dependencies
                    .clone_from(&semantic_dependencies[m.info.id.0 as usize]);
                info
            })
            .collect(),
        types,
        aliases: d.alias_info,
        structs: d.structs,
        enums: d.enums,
        signatures: d.signatures,
        instances,
        generic_functions,
        functions,
        entry,
    };
    verify_hir(&hir)?;
    Ok(hir)
}
pub fn analyze(ast: ParsedAst) -> Result<TypedHir, Vec<Diagnostic>> {
    analyze_bodies(collect_signatures(ast)?)
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
struct InstanceKey {
    function: FunctionId,
    arguments: Vec<TypeId>,
}

struct Monomorphizer<'a> {
    types: &'a mut TypeArena,
    signatures: &'a [FunctionSignature],
    declarations: &'a [GenericHirFunction],
    structs: &'a [StructInfo],
    enums: &'a [EnumInfo],
    ids: BTreeMap<InstanceKey, crate::InstanceId>,
    queue: Vec<InstanceKey>,
    parents: Vec<Option<usize>>,
    current: Option<usize>,
    instances: Vec<FunctionInstanceInfo>,
    functions: Vec<HirFunction>,
}

fn monomorphize(
    types: &mut TypeArena,
    signatures: &[FunctionSignature],
    declarations: &[GenericHirFunction],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    entry: FunctionId,
) -> Result<
    (
        Vec<FunctionInstanceInfo>,
        Vec<HirFunction>,
        crate::InstanceId,
    ),
    Vec<Diagnostic>,
> {
    let mut mono = Monomorphizer {
        types,
        signatures,
        declarations,
        structs,
        enums,
        ids: BTreeMap::new(),
        queue: Vec::new(),
        parents: Vec::new(),
        current: None,
        instances: Vec::new(),
        functions: Vec::new(),
    };
    for signature in signatures {
        if signature.generic_parameters.is_empty() {
            mono.request(
                InstanceKey {
                    function: signature.id,
                    arguments: Vec::new(),
                },
                signature.span,
            )?;
        }
    }
    let entry = *mono
        .ids
        .get(&InstanceKey {
            function: entry,
            arguments: Vec::new(),
        })
        .expect("non-generic entry was seeded");
    let mut cursor = 0;
    while cursor < mono.queue.len() {
        let key = mono.queue[cursor].clone();
        mono.current = Some(cursor);
        mono.instantiate(key)?;
        cursor += 1;
    }
    Ok((mono.instances, mono.functions, entry))
}

impl Monomorphizer<'_> {
    fn request(
        &mut self,
        key: InstanceKey,
        span: Span,
    ) -> Result<crate::InstanceId, Vec<Diagnostic>> {
        if let Some(id) = self.ids.get(&key) {
            return Ok(*id);
        }
        let signature = &self.signatures[key.function.0 as usize];
        if key.arguments.len() != signature.generic_parameters.len() {
            return Err(vec![generic_call_arity(
                &signature.name,
                signature.generic_parameters.len(),
                key.arguments.len(),
                span,
            )]);
        }
        if key
            .arguments
            .iter()
            .any(|argument| self.types.contains_generic(*argument))
        {
            return Err(vec![Diagnostic::new(
                "E0266",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "unresolved generic argument reached monomorphization",
                Some(span),
            )]);
        }
        validate_generic_constraints(
            self.types,
            &signature.generic_parameters,
            &key.arguments,
            &signature.name,
            self.structs,
            self.enums,
            span,
            false,
        )?;
        // Only an instantiation ancestor can establish expanding recursion.
        // Independent calls such as keep<int> and keep<Array<int>> are finite.
        let mut ancestor = self.current;
        let mut structurally_expands = false;
        while let Some(index) = ancestor {
            let previous = &self.queue[index];
            structurally_expands |= previous.function == key.function
                && previous.arguments.len() == key.arguments.len()
                && key
                    .arguments
                    .iter()
                    .zip(&previous.arguments)
                    .all(|(new, old)| type_contains(self.types, *new, *old))
                && key.arguments != previous.arguments;
            ancestor = self.parents[index];
        }
        if structurally_expands
            || self.queue.len() >= 256
            || key
                .arguments
                .iter()
                .any(|argument| type_depth(self.types, *argument) > 32)
        {
            return Err(vec![Diagnostic::new(
                "E0265",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "expanding monomorphization of `{}` exceeds the Vertical-10 safety limit",
                    signature.name
                ),
                Some(span),
            )]);
        }
        let id = crate::InstanceId(self.queue.len() as u32);
        self.ids.insert(key.clone(), id);
        self.queue.push(key);
        self.parents.push(self.current);
        Ok(id)
    }

    fn instantiate(&mut self, key: InstanceKey) -> Result<(), Vec<Diagnostic>> {
        let id = self.ids[&key];
        let signature = self.signatures[key.function.0 as usize].clone();
        let declaration = self.declarations[key.function.0 as usize].clone();
        let substitution = Substitution::new(
            signature
                .generic_parameters
                .iter()
                .map(|parameter| parameter.id),
            key.arguments.iter().copied(),
        );
        let parameters = signature
            .parameters
            .iter()
            .map(|parameter| {
                Ok(ParameterSignature {
                    name: parameter.name.clone(),
                    ty: self.substitute_type(parameter.ty, &substitution, parameter.span)?,
                    mutability: parameter.mutability,
                    default: parameter.default.clone(),
                    span: parameter.span,
                })
            })
            .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?;
        let return_type =
            self.substitute_type(signature.return_type, &substitution, signature.span)?;
        let locals = declaration
            .locals
            .iter()
            .map(|local| {
                Ok(HirLocal {
                    id: local.id,
                    name: local.name.clone(),
                    ty: self.substitute_type(local.ty, &substitution, local.span)?,
                    span: local.span,
                    parameter: local.parameter,
                    source_binding: local.source_binding,
                    mutability: local.mutability,
                    address_taken: local.address_taken,
                })
            })
            .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?;
        let hir_parameters = declaration
            .parameters
            .iter()
            .map(|parameter| {
                Ok(HirParameter {
                    local: parameter.local,
                    ty: self.substitute_type(parameter.ty, &substitution, parameter.span)?,
                    span: parameter.span,
                    mutability: parameter.mutability,
                })
            })
            .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?;
        let mut body = self.substitute_block(&declaration.body, &substitution)?;
        synthesize_ownership(&mut body, &locals, &hir_parameters, self.types)?;
        debug_assert_eq!(id.0 as usize, self.functions.len());
        self.instances.push(FunctionInstanceInfo {
            id,
            function_id: key.function,
            module: signature.module,
            name: signature.name,
            type_arguments: key.arguments,
            parameters,
            return_type,
            span: signature.span,
        });
        self.functions.push(HirFunction {
            id,
            function_id: key.function,
            module: declaration.module,
            parameters: hir_parameters,
            locals,
            body,
            constructor_unwind: declaration.constructor_unwind.clone(),
            span: declaration.span,
        });
        Ok(())
    }

    fn substitute_type(
        &mut self,
        ty: TypeId,
        substitution: &Substitution,
        span: Span,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        self.types
            .substitute(ty, substitution)
            .map_err(|parameter| vec![incomplete_substitution(parameter, span)])
    }

    fn substitute_block(
        &mut self,
        block: &HirBlock,
        substitution: &Substitution,
    ) -> Result<HirBlock, Vec<Diagnostic>> {
        Ok(HirBlock {
            statements: block
                .statements
                .iter()
                .map(|statement| {
                    let kind = match &statement.kind {
                        HirStmtKind::Nop => HirStmtKind::Nop,
                        HirStmtKind::Local { local, initializer } => HirStmtKind::Local {
                            local: *local,
                            initializer: self.substitute_expr(initializer, substitution)?,
                        },
                        HirStmtKind::Assign { place, value } => HirStmtKind::Assign {
                            place: self.substitute_place(place, substitution)?,
                            value: self.substitute_expr(value, substitution)?,
                        },
                        HirStmtKind::StringOutput {
                            function,
                            value,
                            newline,
                        } => HirStmtKind::StringOutput {
                            function: function.clone(),
                            value: self.substitute_expr(value, substitution)?,
                            newline: *newline,
                        },
                        HirStmtKind::ListPush {
                            target,
                            value,
                            mutation,
                        } => HirStmtKind::ListPush {
                            target: self.substitute_place(target, substitution)?,
                            value: self.substitute_expr(value, substitution)?,
                            mutation: *mutation,
                        },
                        HirStmtKind::ListReserve {
                            target,
                            requested_capacity,
                            mutation,
                        } => HirStmtKind::ListReserve {
                            target: self.substitute_place(target, substitution)?,
                            requested_capacity: self
                                .substitute_expr(requested_capacity, substitution)?,
                            mutation: *mutation,
                        },
                        HirStmtKind::If {
                            condition,
                            then_block,
                            else_block,
                        } => HirStmtKind::If {
                            condition: self.substitute_expr(condition, substitution)?,
                            then_block: self.substitute_block(then_block, substitution)?,
                            else_block: else_block
                                .as_ref()
                                .map(|block| self.substitute_block(block, substitution))
                                .transpose()?,
                        },
                        HirStmtKind::While { condition, body } => HirStmtKind::While {
                            condition: self.substitute_expr(condition, substitution)?,
                            body: self.substitute_block(body, substitution)?,
                        },
                        HirStmtKind::ForRange {
                            loop_id,
                            binding,
                            item_type,
                            start,
                            step,
                            end,
                            step_is_implicit,
                            body,
                        } => HirStmtKind::ForRange {
                            loop_id: *loop_id,
                            binding: *binding,
                            item_type: self.substitute_type(
                                *item_type,
                                substitution,
                                statement.span,
                            )?,
                            start: self.substitute_expr(start, substitution)?,
                            step: self.substitute_expr(step, substitution)?,
                            end: self.substitute_expr(end, substitution)?,
                            step_is_implicit: *step_is_implicit,
                            body: self.substitute_block(body, substitution)?,
                        },
                        HirStmtKind::ForCollection {
                            loop_id,
                            binding,
                            iterable_type,
                            item_type,
                            binding_type,
                            category,
                            source,
                            structural_borrow,
                            body,
                        } => HirStmtKind::ForCollection {
                            loop_id: *loop_id,
                            binding: *binding,
                            iterable_type: self.substitute_type(
                                *iterable_type,
                                substitution,
                                statement.span,
                            )?,
                            item_type: self.substitute_type(
                                *item_type,
                                substitution,
                                statement.span,
                            )?,
                            binding_type: self.substitute_type(
                                *binding_type,
                                substitution,
                                statement.span,
                            )?,
                            category: *category,
                            source: match source {
                                CollectionIterationSource::Borrowed(place) => {
                                    CollectionIterationSource::Borrowed(
                                        self.substitute_place(place, substitution)?,
                                    )
                                }
                                CollectionIterationSource::Temporary { root, initializer } => {
                                    CollectionIterationSource::Temporary {
                                        root: *root,
                                        initializer: self
                                            .substitute_expr(initializer, substitution)?,
                                    }
                                }
                            },
                            structural_borrow: *structural_borrow,
                            body: self.substitute_block(body, substitution)?,
                        },
                        HirStmtKind::Match {
                            mode,
                            scrutinee,
                            enum_type,
                            enum_id,
                            arms,
                        } => HirStmtKind::Match {
                            mode: *mode,
                            scrutinee: self.substitute_expr(scrutinee, substitution)?,
                            enum_type: self.substitute_type(
                                *enum_type,
                                substitution,
                                scrutinee.span,
                            )?,
                            enum_id: *enum_id,
                            arms: arms
                                .iter()
                                .map(|arm| {
                                    Ok(HirMatchArm {
                                        variant_id: arm.variant_id,
                                        bindings: arm
                                            .bindings
                                            .iter()
                                            .map(|binding| {
                                                let ty = self.substitute_type(
                                                    binding.ty,
                                                    substitution,
                                                    binding.span,
                                                )?;
                                                Ok(HirMatchBinding {
                                                    local: binding.local,
                                                    payload_index: binding.payload_index,
                                                    ty,
                                                    span: binding.span,
                                                })
                                            })
                                            .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
                                        body: self.substitute_block(&arm.body, substitution)?,
                                        span: arm.span,
                                    })
                                })
                                .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
                        },
                        HirStmtKind::Return { value, drops } => HirStmtKind::Return {
                            value: self.substitute_expr(value, substitution)?,
                            drops: drops.clone(),
                        },
                        HirStmtKind::Break { drops } => HirStmtKind::Break {
                            drops: drops.clone(),
                        },
                        HirStmtKind::Continue { drops } => HirStmtKind::Continue {
                            drops: drops.clone(),
                        },
                        HirStmtKind::Throw {
                            value,
                            class,
                            transfer,
                            drops,
                        } => HirStmtKind::Throw {
                            value: self.substitute_expr(value, substitution)?,
                            class: *class,
                            transfer: *transfer,
                            drops: drops.clone(),
                        },
                        HirStmtKind::Rethrow { catch, drops } => HirStmtKind::Rethrow {
                            catch: *catch,
                            drops: drops.clone(),
                        },
                        HirStmtKind::Try {
                            body,
                            catches,
                            finally,
                        } => HirStmtKind::Try {
                            body: self.substitute_block(body, substitution)?,
                            catches: catches
                                .iter()
                                .map(|catch| {
                                    Ok(HirCatch {
                                        id: catch.id,
                                        class: catch.class,
                                        binding: catch.binding,
                                        body: self.substitute_block(&catch.body, substitution)?,
                                        span: catch.span,
                                    })
                                })
                                .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
                            finally: finally
                                .as_ref()
                                .map(|finally| {
                                    Ok::<HirFinally, Vec<Diagnostic>>(HirFinally {
                                        id: finally.id,
                                        body: self.substitute_block(&finally.body, substitution)?,
                                        span: finally.span,
                                    })
                                })
                                .transpose()?,
                        },
                    };
                    Ok(HirStmt {
                        kind,
                        span: statement.span,
                        compiler_generated: statement.compiler_generated,
                    })
                })
                .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
            exit_drops: block.exit_drops.clone(),
            span: block.span,
        })
    }

    fn substitute_place(
        &mut self,
        place: &HirPlace,
        substitution: &Substitution,
    ) -> Result<HirPlace, Vec<Diagnostic>> {
        Ok(HirPlace {
            base: match &place.base {
                HirPlaceBase::Local(local) => HirPlaceBase::Local(*local),
                HirPlaceBase::Dereference { reference, mutable } => HirPlaceBase::Dereference {
                    reference: Box::new(self.substitute_expr(reference, substitution)?),
                    mutable: *mutable,
                },
            },
            projections: place
                .projections
                .iter()
                .map(|projection| match projection {
                    HirPlaceProjection::Field(field) => Ok(HirPlaceProjection::Field(*field)),
                    HirPlaceProjection::Index {
                        index,
                        column,
                        element_type,
                        checked,
                        semantics,
                    } => Ok(HirPlaceProjection::Index {
                        index: Box::new(self.substitute_expr(index, substitution)?),
                        column: column
                            .as_ref()
                            .map(|c| self.substitute_expr(c, substitution).map(Box::new))
                            .transpose()?,
                        element_type: self.substitute_type(
                            *element_type,
                            substitution,
                            index.span,
                        )?,
                        checked: *checked,
                        semantics: *semantics,
                    }),
                })
                .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
            ty: self.substitute_type(place.ty, substitution, Span::in_source(SourceId(0), 0, 0))?,
        })
    }

    fn substitute_math_op(
        &mut self,
        op: MathElementOp,
        element: TypeId,
        substitution: &Substitution,
        span: Span,
    ) -> Result<MathElementOp, Vec<Diagnostic>> {
        match op {
            MathElementOp::Concrete(_) => Ok(op),
            MathElementOp::Behavioral(behavior) => {
                let ty = self.substitute_type(element, substitution, span)?;
                concrete_behavior_op(self.types, ty, behavior)
                    .map(MathElementOp::Concrete)
                    .ok_or_else(|| vec![Diagnostic::new(
                        "E0348", Phase::Semantic, DiagnosticCategory::Verification,
                        "behavioral mathematical kernel did not resolve to a concrete scalar operation",
                        Some(span),
                    )])
            }
        }
    }

    fn substitute_expr(
        &mut self,
        expression: &HirExpr,
        substitution: &Substitution,
    ) -> Result<HirExpr, Vec<Diagnostic>> {
        let ty = self.substitute_type(expression.ty, substitution, expression.span)?;
        let kind = match &expression.kind {
            HirExprKind::Unit => HirExprKind::Unit,
            HirExprKind::Class(op) => {
                let mapped = op.map(|e| self.substitute_expr(e, substitution), |f| Ok(*f))?;
                let mapped = mapped.map(
                    |e| Ok(e.clone()),
                    |target| match target {
                        HirCallTarget::Declaration(function) => self
                            .request(
                                InstanceKey {
                                    function: *function,
                                    arguments: Vec::new(),
                                },
                                expression.span,
                            )
                            .map(HirCallTarget::Instance),
                        HirCallTarget::Instance(_) => Ok(*target),
                    },
                )?;
                HirExprKind::Class(Box::new(mapped))
            }
            HirExprKind::String(op) => HirExprKind::String(Box::new(
                op.clone().map(|e| self.substitute_expr(&e, substitution))?,
            )),
            HirExprKind::Text { call_site, op } => HirExprKind::Text {
                call_site: *call_site,
                op: Box::new(op.clone().map(|e| self.substitute_expr(&e, substitution))?),
            },
            HirExprKind::Core(op) => HirExprKind::Core(Box::new(
                op.clone().map(|e| self.substitute_expr(&e, substitution))?,
            )),
            HirExprKind::Int(value) => HirExprKind::Int(*value),
            HirExprKind::Float(value) => HirExprKind::Float(*value),
            HirExprKind::Bool(value) => HirExprKind::Bool(*value),
            HirExprKind::NullableNull { nullable_type } => HirExprKind::NullableNull {
                nullable_type: self.substitute_type(
                    *nullable_type,
                    substitution,
                    expression.span,
                )?,
            },
            HirExprKind::NullableInject {
                payload,
                nullable_type,
            } => HirExprKind::NullableInject {
                payload: Box::new(self.substitute_expr(payload, substitution)?),
                nullable_type: self.substitute_type(
                    *nullable_type,
                    substitution,
                    expression.span,
                )?,
            },
            HirExprKind::NullableIsNull { operand } => HirExprKind::NullableIsNull {
                operand: Box::new(self.substitute_expr(operand, substitution)?),
            },
            HirExprKind::NullablePayload {
                source,
                proof,
                access,
            } => HirExprKind::NullablePayload {
                source: self.substitute_place(source, substitution)?,
                proof: *proof,
                access: *access,
            },
            HirExprKind::ShortCircuitAnd { left, right } => HirExprKind::ShortCircuitAnd {
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
            },
            HirExprKind::ShortCircuitOr { left, right } => HirExprKind::ShortCircuitOr {
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
            },
            HirExprKind::LogicalNot { operand } => HirExprKind::LogicalNot {
                operand: Box::new(self.substitute_expr(operand, substitution)?),
            },
            HirExprKind::FunctionRef {
                target,
                function_type,
            } => {
                let function_type =
                    self.substitute_type(*function_type, substitution, expression.span)?;
                let target = match target {
                    HirCallTarget::Declaration(function) => HirCallTarget::Instance(self.request(
                        InstanceKey {
                            function: *function,
                            arguments: Vec::new(),
                        },
                        expression.span,
                    )?),
                    HirCallTarget::Instance(_) => {
                        return Err(vec![Diagnostic::new(
                            "E0266",
                            Phase::Semantic,
                            DiagnosticCategory::Verification,
                            "generic HIR already contains an instance function reference",
                            Some(expression.span),
                        )]);
                    }
                };
                HirExprKind::FunctionRef {
                    target,
                    function_type,
                }
            }
            HirExprKind::Local(local) => HirExprKind::Local(*local),
            HirExprKind::Move(local) => {
                if self.types.guarantees_copy(ty) {
                    HirExprKind::Local(*local)
                } else {
                    HirExprKind::Move(*local)
                }
            }
            HirExprKind::Load(place) => {
                let place = self.substitute_place(place, substitution)?;
                if !self.types.guarantees_copy(place.ty) && place.ty != TypeId::STRING {
                    return Err(vec![Diagnostic::new(
                        "E0293",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "partial move or copy through a place is unsupported for a non-Copy type",
                        Some(expression.span),
                    )]);
                }
                HirExprKind::Load(place)
            }
            HirExprKind::Borrow { place, mutable } => HirExprKind::Borrow {
                place: self.substitute_place(place, substitution)?,
                mutable: *mutable,
            },
            HirExprKind::CallScopedSharedBorrow {
                call_site,
                argument_index,
                pointee_type,
                reference_type,
                source,
                origin,
            } => HirExprKind::CallScopedSharedBorrow {
                call_site: *call_site,
                argument_index: *argument_index,
                pointee_type: self.substitute_type(*pointee_type, substitution, expression.span)?,
                reference_type: self.substitute_type(
                    *reference_type,
                    substitution,
                    expression.span,
                )?,
                source: match source {
                    CallBorrowSource::Place(place) => {
                        CallBorrowSource::Place(self.substitute_place(place, substitution)?)
                    }
                    CallBorrowSource::Temporary(initializer) => CallBorrowSource::Temporary(
                        Box::new(self.substitute_expr(initializer, substitution)?),
                    ),
                },
                origin: *origin,
            },
            HirExprKind::BufferInit {
                element_type,
                length,
                initial,
            } => HirExprKind::BufferInit {
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                length: Box::new(self.substitute_expr(length, substitution)?),
                initial: Box::new(self.substitute_expr(initial, substitution)?),
            },
            HirExprKind::VectorTranspose {
                operand,
                source_type,
            } => HirExprKind::VectorTranspose {
                operand: Box::new(self.substitute_expr(operand, substitution)?),
                source_type: self.substitute_type(*source_type, substitution, expression.span)?,
            },
            HirExprKind::MatrixInit {
                rows,
                columns,
                row_ends,
                element_type,
                elements,
            } => HirExprKind::MatrixInit {
                rows: *rows,
                columns: *columns,
                row_ends: row_ends.clone(),
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                elements: elements
                    .iter()
                    .map(|element| self.substitute_expr(element, substitution))
                    .collect::<Result<Vec<_>, _>>()?,
            },
            HirExprKind::VectorInit {
                element_type,
                elements,
            } => HirExprKind::VectorInit {
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                elements: elements
                    .iter()
                    .map(|element| self.substitute_expr(element, substitution))
                    .collect::<Result<Vec<_>, _>>()?,
            },
            HirExprKind::ArrayInit {
                element_type,
                elements,
            } => HirExprKind::ArrayInit {
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                elements: elements
                    .iter()
                    .map(|element| self.substitute_expr(element, substitution))
                    .collect::<Result<Vec<_>, _>>()?,
            },
            HirExprKind::ArrayFill {
                element_type,
                length,
                initial,
            } => HirExprKind::ArrayFill {
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                length: Box::new(self.substitute_expr(length, substitution)?),
                initial: Box::new(self.substitute_expr(initial, substitution)?),
            },
            HirExprKind::MatrixRows { source } => HirExprKind::MatrixRows {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::MatrixColumns { source } => HirExprKind::MatrixColumns {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::VectorDimension { source } => HirExprKind::VectorDimension {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::ArrayLength { source } => HirExprKind::ArrayLength {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::ListInit {
                element_type,
                elements,
            } => HirExprKind::ListInit {
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                elements: elements
                    .iter()
                    .map(|element| self.substitute_expr(element, substitution))
                    .collect::<Result<Vec<_>, _>>()?,
            },
            HirExprKind::ListLength { source } => HirExprKind::ListLength {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::ListSwapRemove {
                source,
                index,
                element_type,
                effect,
                invalidation,
            } => HirExprKind::ListSwapRemove {
                source: self.substitute_place(source, substitution)?,
                index: Box::new(self.substitute_expr(index, substitution)?),
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                effect: *effect,
                invalidation: *invalidation,
            },
            HirExprKind::ListRemove {
                source,
                index,
                element_type,
                effect,
                invalidation,
            } => HirExprKind::ListRemove {
                source: self.substitute_place(source, substitution)?,
                index: Box::new(self.substitute_expr(index, substitution)?),
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                effect: *effect,
                invalidation: *invalidation,
            },
            HirExprKind::ListPop {
                source,
                element_type,
                effect,
            } => HirExprKind::ListPop {
                source: self.substitute_place(source, substitution)?,
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                effect: *effect,
            },
            HirExprKind::ListCapacity { source } => HirExprKind::ListCapacity {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::MatrixAxisVectorView {
                source,
                fixed_index,
                axis,
                mutable,
                descriptor,
            } => HirExprKind::MatrixAxisVectorView {
                source: self.substitute_place(source, substitution)?,
                fixed_index: Box::new(self.substitute_expr(fixed_index, substitution)?),
                axis: *axis,
                mutable: *mutable,
                descriptor: *descriptor,
            },
            HirExprKind::VectorView {
                source,
                mutable,
                transpose,
                descriptor,
            } => HirExprKind::VectorView {
                source: self.substitute_place(source, substitution)?,
                mutable: *mutable,
                transpose: *transpose,
                descriptor: *descriptor,
            },
            HirExprKind::MatrixView {
                source,
                mutable,
                transpose,
                descriptor,
            } => HirExprKind::MatrixView {
                source: self.substitute_place(source, substitution)?,
                mutable: *mutable,
                transpose: *transpose,
                descriptor: *descriptor,
            },
            HirExprKind::View { source, mutable } => HirExprKind::View {
                source: self.substitute_place(source, substitution)?,
                mutable: *mutable,
            },
            HirExprKind::Call {
                call_site,
                callee,
                type_arguments,
                args,
            } => {
                let HirCallTarget::Declaration(function) = callee else {
                    return Err(vec![Diagnostic::new(
                        "E0266",
                        Phase::Semantic,
                        DiagnosticCategory::Verification,
                        "generic HIR already contains an instance call",
                        Some(expression.span),
                    )]);
                };
                let concrete_arguments = type_arguments
                    .iter()
                    .map(|argument| self.substitute_type(*argument, substitution, expression.span))
                    .collect::<Result<Vec<_>, _>>()?;
                let instance = self.request(
                    InstanceKey {
                        function: *function,
                        arguments: concrete_arguments.clone(),
                    },
                    expression.span,
                )?;
                HirExprKind::Call {
                    call_site: *call_site,
                    callee: HirCallTarget::Instance(instance),
                    type_arguments: concrete_arguments,
                    args: args
                        .iter()
                        .map(|argument| {
                            Ok::<_, Vec<Diagnostic>>(HirCallArgument {
                                binding: argument.binding,
                                initializer: self
                                    .substitute_expr(&argument.initializer, substitution)?,
                                ty: self.substitute_type(
                                    argument.ty,
                                    substitution,
                                    argument.initializer.span,
                                )?,
                                origin: argument.origin,
                            })
                        })
                        .collect::<Result<Vec<_>, _>>()?,
                }
            }
            HirExprKind::IndirectCall {
                call_site,
                callee,
                args,
                signature,
            } => HirExprKind::IndirectCall {
                call_site: *call_site,
                callee: Box::new(self.substitute_expr(callee, substitution)?),
                args: args
                    .iter()
                    .map(|argument| self.substitute_expr(argument, substitution))
                    .collect::<Result<Vec<_>, _>>()?,
                signature: self.substitute_type(*signature, substitution, expression.span)?,
            },
            HirExprKind::StructInit { struct_id, fields } => HirExprKind::StructInit {
                struct_id: *struct_id,
                fields: fields
                    .iter()
                    .map(|(field, value)| Ok((*field, self.substitute_expr(value, substitution)?)))
                    .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
            },
            HirExprKind::EnumInit {
                enum_id,
                variant_id,
                payloads,
            } => HirExprKind::EnumInit {
                enum_id: *enum_id,
                variant_id: *variant_id,
                payloads: payloads
                    .iter()
                    .map(|payload| self.substitute_expr(payload, substitution))
                    .collect::<Result<Vec<_>, _>>()?,
            },
            HirExprKind::Coerce { kind, operand } => HirExprKind::Coerce {
                kind: *kind,
                operand: Box::new(self.substitute_expr(operand, substitution)?),
            },
            HirExprKind::ExplicitCast {
                kind,
                source_type,
                target_type,
                operand,
            } => HirExprKind::ExplicitCast {
                kind: *kind,
                source_type: self.substitute_type(*source_type, substitution, expression.span)?,
                target_type: self.substitute_type(*target_type, substitution, expression.span)?,
                operand: Box::new(self.substitute_expr(operand, substitution)?),
            },
            HirExprKind::Unary { op, operand } => HirExprKind::Unary {
                op: *op,
                operand: Box::new(self.substitute_expr(operand, substitution)?),
            },
            HirExprKind::AlgebraicValue {
                capability: AlgebraicCapability::Zero,
            } => {
                zero_value(self.types, ty, expression.span)
                    .expect("verified Zero substitution")
                    .kind
            }
            HirExprKind::AlgebraicProduct {
                left,
                right,
                element_type,
                product_op,
                product,
            } => HirExprKind::AlgebraicProduct {
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                product_op: self.substitute_math_op(
                    *product_op,
                    *element_type,
                    substitution,
                    expression.span,
                )?,
                product: match product {
                    AlgebraicProductKind::MatrixMatrix {
                        shape_check,
                        output_rows,
                        output_columns,
                        contraction_extent,
                        accumulate_op,
                        zero,
                    } => AlgebraicProductKind::MatrixMatrix {
                        shape_check: *shape_check,
                        output_rows: *output_rows,
                        output_columns: *output_columns,
                        contraction_extent: *contraction_extent,
                        accumulate_op: self.substitute_math_op(
                            *accumulate_op,
                            *element_type,
                            substitution,
                            expression.span,
                        )?,
                        zero: Box::new(self.substitute_expr(zero, substitution)?),
                    },
                    AlgebraicProductKind::MatrixVector {
                        matrix_side,
                        shape_check,
                        result_extent,
                        contraction_extent,
                        accumulate_op,
                        zero,
                    } => AlgebraicProductKind::MatrixVector {
                        matrix_side: *matrix_side,
                        shape_check: *shape_check,
                        result_extent: *result_extent,
                        contraction_extent: *contraction_extent,
                        accumulate_op: self.substitute_math_op(
                            *accumulate_op,
                            *element_type,
                            substitution,
                            expression.span,
                        )?,
                        zero: Box::new(self.substitute_expr(zero, substitution)?),
                    },
                    AlgebraicProductKind::Inner {
                        shape_check,
                        accumulate_op,
                        zero,
                    } => AlgebraicProductKind::Inner {
                        shape_check: *shape_check,
                        accumulate_op: self.substitute_math_op(
                            *accumulate_op,
                            *element_type,
                            substitution,
                            expression.span,
                        )?,
                        zero: Box::new(self.substitute_expr(zero, substitution)?),
                    },
                    AlgebraicProductKind::Outer { rows, columns } => AlgebraicProductKind::Outer {
                        rows: *rows,
                        columns: *columns,
                    },
                },
            },
            HirExprKind::VectorScalarMultiply {
                left,
                right,
                scalar_side,
                element_type,
                op,
                orientation,
            } => HirExprKind::VectorScalarMultiply {
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
                scalar_side: *scalar_side,
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                op: self.substitute_math_op(*op, *element_type, substitution, expression.span)?,
                orientation: *orientation,
            },
            HirExprKind::MatrixScalarMultiply {
                left,
                right,
                scalar_side,
                element_type,
                op,
            } => HirExprKind::MatrixScalarMultiply {
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
                scalar_side: *scalar_side,
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                op: self.substitute_math_op(*op, *element_type, substitution, expression.span)?,
            },
            HirExprKind::VectorElementwiseBinary {
                shape_check,
                source_op,
                left,
                right,
                element_type,
                op,
                orientation,
            } => HirExprKind::VectorElementwiseBinary {
                shape_check: *shape_check,
                source_op: *source_op,
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                op: self.substitute_math_op(*op, *element_type, substitution, expression.span)?,
                orientation: *orientation,
            },
            HirExprKind::MatrixElementwiseBinary {
                shape_check,
                source_op,
                left,
                right,
                element_type,
                op,
            } => HirExprKind::MatrixElementwiseBinary {
                shape_check: *shape_check,
                source_op: *source_op,
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                op: self.substitute_math_op(*op, *element_type, substitution, expression.span)?,
            },
            HirExprKind::CapabilityBinary {
                behavior,
                left,
                right,
            } => {
                let op = concrete_behavior_op(self.types, ty, *behavior).ok_or_else(|| {
                    vec![Diagnostic::new(
                        "E0348",
                        Phase::Semantic,
                        DiagnosticCategory::Verification,
                        "capability operation did not resolve to a concrete built-in scalar",
                        Some(expression.span),
                    )]
                })?;
                HirExprKind::Binary {
                    op,
                    left: Box::new(self.substitute_expr(left, substitution)?),
                    right: Box::new(self.substitute_expr(right, substitution)?),
                }
            }
            HirExprKind::Binary { op, left, right } => HirExprKind::Binary {
                op: *op,
                left: Box::new(self.substitute_expr(left, substitution)?),
                right: Box::new(self.substitute_expr(right, substitution)?),
            },
        };
        Ok(HirExpr {
            kind,
            ty,
            span: expression.span,
        })
    }
}

fn type_depth(types: &TypeArena, ty: TypeId) -> usize {
    match types.get(ty) {
        Some(TypeData::Reference { pointee, .. }) => 1 + type_depth(types, *pointee),
        Some(TypeData::Nullable(payload)) => 1 + type_depth(types, *payload),
        Some(
            TypeData::Buffer { element }
            | TypeData::Matrix { element }
            | TypeData::Vector { element, .. }
            | TypeData::Array { element }
            | TypeData::List { element }
            | TypeData::View { element, .. }
            | TypeData::VectorView { element, .. }
            | TypeData::MatrixView { element, .. },
        ) => 1 + type_depth(types, *element),
        Some(TypeData::StructInstance(_, args) | TypeData::EnumInstance(_, args)) => {
            1 + types
                .arguments(*args)
                .unwrap()
                .iter()
                .map(|argument| type_depth(types, *argument))
                .max()
                .unwrap_or(0)
        }
        _ => 1,
    }
}

fn type_contains(types: &TypeArena, outer: TypeId, needle: TypeId) -> bool {
    outer == needle
        || match types.get(outer) {
            Some(TypeData::StructInstance(_, args) | TypeData::EnumInstance(_, args)) => {
                types.arguments(*args).is_some_and(|arguments| {
                    arguments
                        .iter()
                        .any(|argument| type_contains(types, *argument, needle))
                })
            }
            Some(TypeData::Reference { pointee, .. }) => type_contains(types, *pointee, needle),
            Some(TypeData::Nullable(payload)) => type_contains(types, *payload, needle),
            Some(
                TypeData::Buffer { element }
                | TypeData::Matrix { element }
                | TypeData::Vector { element, .. }
                | TypeData::Array { element }
                | TypeData::List { element }
                | TypeData::View { element, .. }
                | TypeData::VectorView { element, .. }
                | TypeData::MatrixView { element, .. },
            ) => type_contains(types, *element, needle),
            _ => false,
        }
}

fn compute_concrete_layouts(
    types: &mut TypeArena,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    target: TargetProperties,
) -> Result<(), Vec<Diagnostic>> {
    fn concrete_layout(
        types: &mut TypeArena,
        structs: &[StructInfo],
        enums: &[EnumInfo],
        target: TargetProperties,
        ty: TypeId,
        visiting: &mut BTreeSet<TypeId>,
    ) -> Result<TypeLayout, Vec<Diagnostic>> {
        if let Some((size, align)) = types.cached_layout(ty) {
            return Ok(TypeLayout { size, align });
        }
        let data = types.get(ty).copied().ok_or_else(|| {
            vec![Diagnostic::new(
                "E0266",
                Phase::Semantic,
                DiagnosticCategory::Verification,
                "layout requested for invalid type",
                None,
            )]
        })?;
        let scalar = match data {
            TypeData::Bool => Some(TypeLayout { size: 1, align: 1 }),
            TypeData::Char | TypeData::Float(FloatType::Float32) => {
                Some(TypeLayout { size: 4, align: 4 })
            }
            TypeData::Integer(integer) => {
                let bytes = u64::from(integer.bits(target) / 8);
                Some(TypeLayout {
                    size: bytes,
                    align: bytes,
                })
            }
            TypeData::Float(FloatType::Float64) => Some(TypeLayout { size: 8, align: 8 }),
            TypeData::Struct(id) => Some(structs[id.0 as usize].layout),
            TypeData::Enum(id) => Some(enums[id.0 as usize].layout),
            TypeData::String
            | TypeData::Class(_)
            | TypeData::ClassToken { .. }
            | TypeData::Interface(_)
            | TypeData::InterfaceKeepalive { .. }
            | TypeData::Reference { .. }
            | TypeData::Function { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes,
                    align: bytes,
                })
            }
            TypeData::Buffer { .. }
            | TypeData::Vector { .. }
            | TypeData::Array { .. }
            | TypeData::View { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes * 2,
                    align: bytes,
                })
            }
            TypeData::MatrixView { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes * 5,
                    align: bytes,
                })
            }
            TypeData::VectorView { .. } | TypeData::Matrix { .. } | TypeData::List { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes * 3,
                    align: bytes,
                })
            }
            TypeData::Void
            | TypeData::GenericParam(_)
            | TypeData::StructInstance(_, _)
            | TypeData::EnumInstance(_, _)
            | TypeData::Nullable(_) => None,
        };
        if let Some(layout) = scalar {
            return Ok(layout);
        }
        if matches!(data, TypeData::GenericParam(_)) {
            return Err(vec![Diagnostic::new(
                "E0266",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "unresolved generic parameter has no concrete layout",
                None,
            )]);
        }
        if !visiting.insert(ty) {
            return Err(vec![Diagnostic::new(
                "E0267",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "generic recursive by-value layout has infinite size",
                None,
            )]);
        }
        let layout =
            match data {
                TypeData::Nullable(payload) => {
                    let payload_layout =
                        concrete_layout(types, structs, enums, target, payload, visiting)?;
                    if matches!(
                        types.get(payload),
                        Some(
                            TypeData::String
                                | TypeData::Class(_)
                                | TypeData::Reference { .. }
                                | TypeData::Function { .. }
                        )
                    ) {
                        payload_layout
                    } else {
                        let offset = align_up(1, payload_layout.align);
                        TypeLayout {
                            size: align_up(offset + payload_layout.size, payload_layout.align),
                            align: payload_layout.align,
                        }
                    }
                }
                TypeData::StructInstance(id, args) => {
                    let info = &structs[id.0 as usize];
                    let arguments = types
                        .arguments(args)
                        .expect("valid struct arguments")
                        .to_vec();
                    let substitution = Substitution::new(
                        info.generic_parameters.iter().map(|parameter| parameter.id),
                        arguments,
                    );
                    let mut offset = 0_u64;
                    let mut align = 1_u64;
                    for field in &info.fields {
                        let field_ty =
                            types
                                .substitute(field.ty, &substitution)
                                .map_err(|parameter| {
                                    vec![incomplete_substitution(parameter, field.span)]
                                })?;
                        let field_layout =
                            concrete_layout(types, structs, enums, target, field_ty, visiting)?;
                        offset = align_up(offset, field_layout.align);
                        offset += field_layout.size;
                        align = align.max(field_layout.align);
                    }
                    TypeLayout {
                        size: align_up(offset, align),
                        align,
                    }
                }
                TypeData::EnumInstance(id, args) => {
                    let info = &enums[id.0 as usize];
                    let arguments = types
                        .arguments(args)
                        .expect("valid enum arguments")
                        .to_vec();
                    let substitution = Substitution::new(
                        info.generic_parameters.iter().map(|parameter| parameter.id),
                        arguments,
                    );
                    let mut offset = 4_u64;
                    let mut align = 4_u64;
                    for variant in &info.variants {
                        let mut tuple_size = 0_u64;
                        let mut tuple_align = 1_u64;
                        for payload in &variant.payloads {
                            let payload_ty = types.substitute(payload.ty, &substitution).map_err(
                                |parameter| vec![incomplete_substitution(parameter, payload.span)],
                            )?;
                            let payload_layout = concrete_layout(
                                types, structs, enums, target, payload_ty, visiting,
                            )?;
                            tuple_size =
                                align_up(tuple_size, payload_layout.align) + payload_layout.size;
                            tuple_align = tuple_align.max(payload_layout.align);
                        }
                        offset = align_up(offset, tuple_align) + align_up(tuple_size, tuple_align);
                        align = align.max(tuple_align);
                    }
                    TypeLayout {
                        size: align_up(offset, align),
                        align,
                    }
                }
                _ => unreachable!(),
            };
        visiting.remove(&ty);
        types.cache_layout(ty, layout.size, layout.align);
        Ok(layout)
    }

    let concrete = types
        .entries()
        .filter_map(|(ty, data)| {
            (matches!(
                data,
                TypeData::StructInstance(_, _) | TypeData::EnumInstance(_, _)
            ) && !types.contains_generic(ty))
            .then_some(ty)
        })
        .collect::<Vec<_>>();
    for ty in concrete {
        concrete_layout(types, structs, enums, target, ty, &mut BTreeSet::new())?;
    }
    Ok(())
}

fn analyze_function(
    f: &AstFunction,
    id: FunctionId,
    module: ModuleId,
    d: &DeclaredProgram,
    types: &mut TypeArena,
    target: TargetProperties,
) -> Result<(GenericHirFunction, BTreeSet<ModuleId>), Vec<Diagnostic>> {
    let sig = &d.signatures[id.0 as usize];
    crate::verify_class_signature(
        types,
        id,
        module,
        &sig.parameters.iter().map(|p| p.ty).collect::<Vec<_>>(),
        sig.return_type,
    )
    .map_err(|m| vec![classes::error("E0402", m, sig.span)])?;
    let class_method = types.class_method(id).map(|(c, m)| (c, m.clone()));
    let mut a = Analyzer {
        scopes: vec![BTreeMap::new()],
        locals: vec![],
        signatures: &d.signatures,
        names: &d.names,
        imports: &d.imports,
        import_bindings: &d.import_bindings,
        used_modules: BTreeSet::new(),
        module_names: &d.module_names,
        aliases: &d.aliases,
        types,
        structs: &d.structs,
        enums: &d.enums,
        struct_names: &d.struct_names,
        enum_names: &d.enum_names,
        variant_names: &d.variant_names,
        field_names: &d.field_names,
        generic_scope: sig
            .generic_parameters
            .iter()
            .map(|parameter| (parameter.name.clone(), parameter.ty))
            .collect(),
        struct_arities: &d.struct_arities,
        enum_arities: &d.enum_arities,
        module,
        return_type: sig.return_type,
        class_method,
        initialized_fields: BTreeSet::new(),
        active_catches: Vec::new(),
        next_catch: 0,
        loop_depth: 0,
        inside_finally: 0,
        next_finally: 0,
        next_loop: 0,
        next_call_site: 0,
        default_forbidden: None,
        null_states: BTreeMap::new(),
        next_non_null_proof: 0,
        target,
    };
    let mut parameters = vec![];
    for p in &sig.parameters {
        if a.import_bindings[module.0 as usize].contains(&p.name) {
            return Err(vec![Diagnostic::new(
                "E0235",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!(
                    "parameter `{}` conflicts with a namespace import binding",
                    p.name
                ),
                Some(p.span),
            )]);
        }
        if a.scopes[0].contains_key(&p.name) {
            return Err(vec![duplicate("parameter", &p.name, p.span)]);
        }
        let local = LocalId(a.locals.len() as u32);
        a.locals.push(HirLocal {
            id: local,
            name: p.name.clone(),
            ty: p.ty,
            span: p.span,
            parameter: true,
            source_binding: true,
            mutability: p.mutability,
            address_taken: false,
        });
        a.scopes[0].insert(p.name.clone(), local);
        if a.types.nullable_payload(p.ty).is_some() {
            a.null_states.insert(local, NullState::Unknown);
        }
        parameters.push(HirParameter {
            local,
            ty: p.ty,
            span: p.span,
            mutability: p.mutability,
        });
    }
    a.validate_declared_defaults(sig, &parameters)?;
    let mut ast_body = f.body.clone();
    if a.class_method.as_ref().is_some_and(|(c, m)| m.initializing && a.types.classes[c.0 as usize].base.is_some())
        && !ast_body.statements.first().is_some_and(|s| matches!(&s.kind, AstStmtKind::Expr(AstExpr { kind: AstExprKind::Call { callee, .. }, .. }) if callee == "$base")) {
        ast_body.statements.insert(0, crate::AstStmt { kind: AstStmtKind::Expr(AstExpr { kind: AstExprKind::Call { callee: "$base".into(), args: Vec::new(), type_arguments: Vec::new() }, span: f.span }), span: f.span });
    }
    let mut body = a.block(&ast_body, false)?;
    if id == d.entry && !definitely_returns(&body) {
        // The parser's block span ends immediately after its closing `}`.
        // Normalize before ownership so ordinary return cleanup is synthesized.
        let span = Span::in_source(body.span.source, body.span.end - 1, body.span.end);
        body.statements.push(HirStmt {
            kind: HirStmtKind::Return {
                value: HirExpr {
                    kind: HirExprKind::Int(0),
                    ty: TypeId::INT64,
                    span,
                },
                drops: Vec::new(),
            },
            span,
            compiler_generated: true,
        });
    }
    if sig.return_type == TypeId::VOID && !definitely_returns(&body) {
        let span = Span::in_source(body.span.source, body.span.end - 1, body.span.end);
        body.statements.push(HirStmt {
            kind: HirStmtKind::Return {
                value: HirExpr {
                    kind: HirExprKind::Unit,
                    ty: TypeId::VOID,
                    span,
                },
                drops: Vec::new(),
            },
            span,
            compiler_generated: true,
        });
    }
    if !definitely_returns(&body) {
        return Err(vec![Diagnostic::new(
            "E0207",
            Phase::Semantic,
            DiagnosticCategory::Type,
            format!(
                "every reachable path through `{}` must return {}",
                sig.name, sig.return_type
            ),
            Some(f.body.span),
        )]);
    }
    synthesize_ownership(&mut body, &a.locals, &parameters, a.types)?;
    let constructor_unwind = a
        .class_method
        .as_ref()
        .filter(|(_, method)| method.initializing)
        .map(|(class, _)| crate::ConstructorUnwindPlan {
            class: *class,
            receiver: parameters[0].local,
            cleanup_fields: a.types.classes()[class.0 as usize]
                .destruction
                .iter()
                .filter_map(|step| match step {
                    crate::ClassDropStep::Field { field, .. } => Some(*field),
                    crate::ClassDropStep::Free { .. } => None,
                })
                .collect(),
        });
    let function = GenericHirFunction {
        id,
        module,
        parameters,
        locals: a.locals,
        body,
        constructor_unwind,
        span: f.span,
    };
    Ok((function, a.used_modules))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum OwnerState {
    Uninitialized,
    Owned,
    Moved,
    MaybeMoved,
    Dropped,
}

struct OwnershipAnalysis<'a> {
    types: &'a TypeArena,
    locals: &'a [HirLocal],
    state: Vec<OwnerState>,
    provenance: Vec<Option<LocalId>>,
    active: Vec<LocalId>,
    borrowed: Vec<BTreeSet<LocalId>>,
    storage_borrowed: Vec<BTreeSet<LocalId>>,
    buffer_lengths: Vec<Option<u64>>,
    matrix_shapes: Vec<Option<(u64, u64)>>,
    storage_ranges: Vec<Vec<(LocalId, Option<u64>)>>,
    iteration_element_borrowed: Vec<BTreeSet<LocalId>>,
    borrow_indices: Vec<Option<u64>>,
    storage_references: Vec<bool>,
    loop_boundaries: Vec<usize>,
}

fn synthesize_ownership(
    body: &mut HirBlock,
    locals: &[HirLocal],
    parameters: &[HirParameter],
    types: &TypeArena,
) -> Result<(), Vec<Diagnostic>> {
    let mut analysis = OwnershipAnalysis {
        types,
        locals,
        state: vec![OwnerState::Uninitialized; locals.len()],
        provenance: vec![None; locals.len()],
        active: Vec::new(),
        borrowed: Vec::new(),
        storage_borrowed: Vec::new(),
        buffer_lengths: vec![None; locals.len()],
        matrix_shapes: vec![None; locals.len()],
        storage_ranges: Vec::new(),
        iteration_element_borrowed: Vec::new(),
        borrow_indices: vec![None; locals.len()],
        storage_references: vec![false; locals.len()],
        loop_boundaries: Vec::new(),
    };
    for parameter in parameters {
        // An incoming view borrows caller storage. Its parameter is the local
        // proxy root, so references and descriptor copies keep that ancestry.
        if types.mathematical_view_info(parameter.ty).is_some() {
            analysis.provenance[parameter.local.0 as usize] = Some(parameter.local);
        }
        if !types.guarantees_copy(parameter.ty) {
            analysis.state[parameter.local.0 as usize] = OwnerState::Owned;
            analysis.active.push(parameter.local);
        }
    }
    analysis.block(body, false)
}

impl OwnershipAnalysis<'_> {
    fn error(&self, code: &'static str, message: impl Into<String>, span: Span) -> Vec<Diagnostic> {
        vec![Diagnostic::new(
            code,
            Phase::Semantic,
            DiagnosticCategory::Type,
            message,
            Some(span),
        )]
    }

    fn is_borrowed(&self, local: LocalId) -> bool {
        self.borrowed.iter().any(|scope| scope.contains(&local))
    }

    fn has_live_storage_borrow(&self, local: LocalId) -> bool {
        self.storage_borrowed
            .iter()
            .any(|scope| scope.contains(&local))
    }

    fn require_owned(&self, local: LocalId, span: Span) -> Result<(), Vec<Diagnostic>> {
        if self.state[local.0 as usize] == OwnerState::MaybeMoved {
            return Err(self.error(
                "E0303",
                format!(
                    "use of maybe-moved non-Copy local `{}` after conditional ownership transfer",
                    self.locals[local.0 as usize].name
                ),
                span,
            ));
        }
        if self.state[local.0 as usize] != OwnerState::Owned {
            return Err(self.error(
                "E0291",
                format!(
                    "use after move of non-Copy local `{}`",
                    self.locals[local.0 as usize].name
                ),
                span,
            ));
        }
        Ok(())
    }

    fn move_local(&mut self, local: LocalId, span: Span) -> Result<(), Vec<Diagnostic>> {
        self.require_owned(local, span)?;
        if self.is_borrowed(local) {
            return Err(self.error(
                "E0292",
                format!(
                    "cannot move `{}` while a derived reference/view remains live",
                    self.locals[local.0 as usize].name
                ),
                span,
            ));
        }
        self.state[local.0 as usize] = OwnerState::Moved;
        Ok(())
    }

    fn block(&mut self, block: &mut HirBlock, nested: bool) -> Result<(), Vec<Diagnostic>> {
        let active_start = self.active.len();
        self.borrowed.push(BTreeSet::new());
        self.storage_borrowed.push(BTreeSet::new());
        self.storage_ranges.push(Vec::new());
        self.iteration_element_borrowed.push(BTreeSet::new());
        for statement in &mut block.statements {
            if matches!(
                statement.kind,
                HirStmtKind::If { .. }
                    | HirStmtKind::While { .. }
                    | HirStmtKind::ForCollection { .. }
                    | HirStmtKind::Match { .. }
            ) {
                self.matrix_shapes.fill(None);
            }
            match &mut statement.kind {
                HirStmtKind::Nop => {}
                HirStmtKind::Local { local, initializer } => {
                    self.expr(initializer)?;
                    if let Some(owner) = self.derived_owner(initializer) {
                        self.provenance[local.0 as usize] = Some(owner);
                        self.borrowed.last_mut().unwrap().insert(owner);
                        if self.is_list_storage_borrow(initializer) {
                            self.storage_borrowed.last_mut().unwrap().insert(owner);
                            let index = self.storage_index(initializer);
                            self.borrow_indices[local.0 as usize] = index;
                            self.storage_references[local.0 as usize] = true;
                            self.storage_ranges.last_mut().unwrap().push((owner, index));
                        }
                    }
                    if !self.types.guarantees_copy(self.locals[local.0 as usize].ty) {
                        self.buffer_lengths[local.0 as usize] = self.known_length(initializer);
                        self.matrix_shapes[local.0 as usize] = self.known_matrix_shape(initializer);
                        self.state[local.0 as usize] = OwnerState::Owned;
                        self.active.push(*local);
                    } else if self
                        .types
                        .borrowed_view_info(self.locals[local.0 as usize].ty)
                        .is_some()
                    {
                        self.buffer_lengths[local.0 as usize] = self.known_length(initializer);
                        self.matrix_shapes[local.0 as usize] = self.known_matrix_shape(initializer);
                    }
                }
                HirStmtKind::Assign { place, value } => {
                    self.expr(value)?;
                    self.place(place, statement.span)?;
                    if !self.types.guarantees_copy(place.ty)
                        && place.projections.iter().any(|projection| {
                            matches!(projection, HirPlaceProjection::Index { .. })
                        })
                        && self.owner_of_place(place).is_some_and(|owner| {
                            self.iteration_element_borrowed
                                .iter()
                                .any(|scope| scope.contains(&owner))
                        })
                    {
                        return Err(self.error(
                            "E0446",
                            "cannot replace a non-Copy collection slot while the current iteration element borrow is live",
                            statement.span,
                        ));
                    }
                    if let HirPlaceBase::Local(local) = place.base
                        && place.projections.is_empty()
                        && !self.types.guarantees_copy(self.locals[local.0 as usize].ty)
                    {
                        if self.is_borrowed(local) {
                            return Err(self.error(
                                "E0292",
                                "cannot replace a non-Copy value while a derived reference/view remains live",
                                statement.span,
                            ));
                        }
                        self.state[local.0 as usize] = OwnerState::Owned;
                        self.buffer_lengths[local.0 as usize] = self.known_length(value);
                        self.matrix_shapes[local.0 as usize] = self.known_matrix_shape(value);
                    }
                }
                HirStmtKind::ListPush { target, value, .. } => {
                    self.expr(value)?;
                    self.structural_mutation(target, statement.span)?;
                    if let Some(local) = self.local_root(target) {
                        self.buffer_lengths[local.0 as usize] = None;
                    }
                }
                HirStmtKind::ListReserve {
                    target,
                    requested_capacity,
                    ..
                } => {
                    self.expr(requested_capacity)?;
                    self.structural_mutation(target, statement.span)?;
                }
                HirStmtKind::StringOutput { value, .. } => self.expr(value)?,
                HirStmtKind::Return { value, drops } => {
                    self.expr(value)?;
                    *drops = self
                        .active
                        .iter()
                        .rev()
                        .copied()
                        .filter_map(|local| {
                            if !self.types.needs_drop(self.locals[local.0 as usize].ty) {
                                return None;
                            }
                            match self.state[local.0 as usize] {
                                OwnerState::Owned => Some(HirDrop::Unconditional(local)),
                                OwnerState::MaybeMoved => Some(HirDrop::Conditional(local)),
                                _ => None,
                            }
                        })
                        .collect();
                    for local in drops.iter().copied().map(HirDrop::local) {
                        self.state[local.0 as usize] = OwnerState::Dropped;
                    }
                }
                HirStmtKind::Break { drops } | HirStmtKind::Continue { drops } => {
                    let boundary = *self
                        .loop_boundaries
                        .last()
                        .expect("verified HIR loop transfer has a loop");
                    *drops = self.active[boundary..]
                        .iter()
                        .rev()
                        .copied()
                        .filter_map(|local| {
                            if !self.types.needs_drop(self.locals[local.0 as usize].ty) {
                                return None;
                            }
                            match self.state[local.0 as usize] {
                                OwnerState::Owned => Some(HirDrop::Unconditional(local)),
                                OwnerState::MaybeMoved => Some(HirDrop::Conditional(local)),
                                _ => None,
                            }
                        })
                        .collect();
                    for local in drops.iter().copied().map(HirDrop::local) {
                        self.state[local.0 as usize] = OwnerState::Dropped;
                    }
                }
                HirStmtKind::Throw { value, drops, .. } => {
                    self.expr(value)?;
                    *drops = self
                        .active
                        .iter()
                        .rev()
                        .copied()
                        .filter_map(|local| {
                            if !self.types.needs_drop(self.locals[local.0 as usize].ty) {
                                return None;
                            }
                            match self.state[local.0 as usize] {
                                OwnerState::Owned => Some(HirDrop::Unconditional(local)),
                                OwnerState::MaybeMoved => Some(HirDrop::Conditional(local)),
                                _ => None,
                            }
                        })
                        .collect();
                    for local in drops.iter().copied().map(HirDrop::local) {
                        self.state[local.0 as usize] = OwnerState::Dropped;
                    }
                }
                HirStmtKind::Rethrow { drops, .. } => {
                    *drops = self
                        .active
                        .iter()
                        .rev()
                        .copied()
                        .filter_map(|local| {
                            if !self.types.needs_drop(self.locals[local.0 as usize].ty) {
                                return None;
                            }
                            match self.state[local.0 as usize] {
                                OwnerState::Owned => Some(HirDrop::Unconditional(local)),
                                OwnerState::MaybeMoved => Some(HirDrop::Conditional(local)),
                                _ => None,
                            }
                        })
                        .collect();
                    for local in drops.iter().copied().map(HirDrop::local) {
                        self.state[local.0 as usize] = OwnerState::Dropped;
                    }
                }
                HirStmtKind::Try {
                    body,
                    catches,
                    finally,
                } => {
                    let before = self.state.clone();
                    let before_active = self.active.len();
                    self.block(body, true)?;
                    let mut continuing = (!definitely_returns(body)).then(|| self.state.clone());
                    for catch in catches {
                        self.state.clone_from(&before);
                        self.active.truncate(before_active);
                        self.state[catch.binding.0 as usize] = OwnerState::Owned;
                        self.active.push(catch.binding);
                        self.block(&mut catch.body, true)?;
                        if definitely_returns(&catch.body) {
                            self.active.pop();
                        } else {
                            if self
                                .types
                                .needs_drop(self.locals[catch.binding.0 as usize].ty)
                            {
                                catch
                                    .body
                                    .exit_drops
                                    .push(HirDrop::Unconditional(catch.binding));
                                self.state[catch.binding.0 as usize] = OwnerState::Dropped;
                            }
                            self.active.pop();
                            if let Some(merged) = &mut continuing {
                                for local in &self.active {
                                    let index = local.0 as usize;
                                    merged[index] =
                                        merge_owner_state(merged[index], self.state[index]);
                                }
                            } else {
                                continuing = Some(self.state.clone());
                            }
                        }
                    }
                    self.state = continuing.unwrap_or(before);
                    self.active.truncate(before_active);
                    if let Some(finally) = finally {
                        self.block(&mut finally.body, true)?;
                    }
                }
                HirStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => {
                    self.expr(condition)?;
                    let before = self.state.clone();
                    let before_lengths = self.buffer_lengths.clone();
                    let borrowed = self.borrowed.clone();
                    self.block(then_block, true)?;
                    let after_then = self.state.clone();
                    let after_then_lengths = self.buffer_lengths.clone();
                    let then_returns = definitely_returns(then_block);
                    self.state.clone_from(&before);
                    self.buffer_lengths.clone_from(&before_lengths);
                    self.matrix_shapes.fill(None);
                    self.borrowed.clone_from(&borrowed);
                    if let Some(else_block) = else_block {
                        self.block(else_block, true)?;
                    }
                    let after_else = self.state.clone();
                    let after_else_lengths = self.buffer_lengths.clone();
                    let else_returns = else_block.as_ref().is_some_and(definitely_returns);
                    for local in &self.active {
                        let index = local.0 as usize;
                        self.state[index] = match (then_returns, else_returns) {
                            (true, true) => before[index],
                            (true, false) => after_else[index],
                            (false, true) => after_then[index],
                            (false, false) => {
                                merge_owner_state(after_then[index], after_else[index])
                            }
                        };
                        self.buffer_lengths[index] = match (then_returns, else_returns) {
                            (true, true) => before_lengths[index],
                            (true, false) => after_else_lengths[index],
                            (false, true) => after_then_lengths[index],
                            (false, false)
                                if after_then_lengths[index] == after_else_lengths[index] =>
                            {
                                after_then_lengths[index]
                            }
                            (false, false) => None,
                        };
                    }
                    self.borrowed = borrowed;
                    self.matrix_shapes.fill(None);
                }
                HirStmtKind::While { condition, body } => {
                    // A loop can revisit pop with a shorter prefix. Fixed-size
                    // Array/Buffer length facts remain valid across backedges.
                    for local in self.locals {
                        if self.types.list_element(local.ty).is_some() {
                            self.buffer_lengths[local.id.0 as usize] = None;
                        }
                    }
                    self.expr(condition)?;
                    let before = self.state.clone();
                    let before_lengths = self.buffer_lengths.clone();
                    self.loop_boundaries.push(self.active.len());
                    self.block(body, true)?;
                    self.loop_boundaries.pop();
                    let after_lengths = self.buffer_lengths.clone();
                    for local in &self.active {
                        let index = local.0 as usize;
                        if self.state[index] != before[index] {
                            return Err(self.error(
                                "E0295",
                                "ownership state conflicts across a loop backedge",
                                statement.span,
                            ));
                        }
                        self.buffer_lengths[index] =
                            if before_lengths[index] == after_lengths[index] {
                                before_lengths[index]
                            } else {
                                None
                            };
                    }
                    self.state = before;
                    self.matrix_shapes.fill(None);
                }
                HirStmtKind::ForRange {
                    start,
                    step,
                    end,
                    body,
                    ..
                } => {
                    self.expr(start)?;
                    self.expr(step)?;
                    self.expr(end)?;
                    let before = self.state.clone();
                    self.loop_boundaries.push(self.active.len());
                    self.block(body, true)?;
                    self.loop_boundaries.pop();
                    for local in &self.active {
                        let index = local.0 as usize;
                        if self.state[index] != before[index] {
                            return Err(self.error(
                                "E0295",
                                "ownership state conflicts across a range loop backedge",
                                statement.span,
                            ));
                        }
                    }
                    self.state = before;
                    self.matrix_shapes.fill(None);
                }
                HirStmtKind::ForCollection {
                    binding,
                    category,
                    source,
                    structural_borrow,
                    body,
                    ..
                } => {
                    let (owner, temporary) = match source {
                        CollectionIterationSource::Borrowed(place) => {
                            self.place(place, statement.span)?;
                            (
                                self.owner_of_place(place).ok_or_else(|| {
                                    self.error(
                                        "E0445",
                                        "collection iteration requires stable owner provenance",
                                        statement.span,
                                    )
                                })?,
                                false,
                            )
                        }
                        CollectionIterationSource::Temporary { root, initializer } => {
                            self.expr(initializer)?;
                            self.state[root.0 as usize] = OwnerState::Owned;
                            self.buffer_lengths[root.0 as usize] = self.known_length(initializer);
                            self.active.push(*root);
                            (*root, true)
                        }
                    };
                    self.borrowed.last_mut().unwrap().insert(owner);
                    if *structural_borrow {
                        self.storage_borrowed.last_mut().unwrap().insert(owner);
                        self.storage_ranges.last_mut().unwrap().push((owner, None));
                    }
                    if *category == IterationBindingCategory::SharedElementBorrow {
                        self.provenance[binding.0 as usize] = Some(owner);
                        self.storage_references[binding.0 as usize] = true;
                        self.borrowed.last_mut().unwrap().insert(owner);
                        self.storage_borrowed.last_mut().unwrap().insert(owner);
                        self.storage_ranges.last_mut().unwrap().push((owner, None));
                        self.iteration_element_borrowed
                            .last_mut()
                            .unwrap()
                            .insert(owner);
                    }
                    let before = self.state.clone();
                    let before_lengths = self.buffer_lengths.clone();
                    self.loop_boundaries.push(self.active.len());
                    self.block(body, true)?;
                    self.loop_boundaries.pop();
                    if !definitely_returns(body) {
                        for local in &self.active {
                            let index = local.0 as usize;
                            if self.state[index] != before[index] {
                                return Err(self.error(
                                    "E0295",
                                    "ownership state conflicts across a collection loop backedge",
                                    statement.span,
                                ));
                            }
                        }
                    }
                    self.state = before;
                    self.buffer_lengths = before_lengths;
                    self.borrowed.last_mut().unwrap().remove(&owner);
                    if *structural_borrow
                        || *category == IterationBindingCategory::SharedElementBorrow
                    {
                        self.storage_borrowed.last_mut().unwrap().remove(&owner);
                        self.storage_ranges
                            .last_mut()
                            .unwrap()
                            .retain(|(root, _)| *root != owner);
                    }
                    self.iteration_element_borrowed
                        .last_mut()
                        .unwrap()
                        .remove(&owner);
                    if temporary {
                        self.state[owner.0 as usize] = OwnerState::Dropped;
                        let removed = self.active.pop();
                        debug_assert_eq!(removed, Some(owner));
                    }
                    self.matrix_shapes.fill(None);
                }
                HirStmtKind::Match {
                    mode,
                    scrutinee,
                    arms,
                    ..
                } => {
                    self.expr(scrutinee)?;
                    let borrowed_owner = (*mode != MatchMode::Value)
                        .then(|| self.derived_owner(scrutinee))
                        .flatten();
                    let before = self.state.clone();
                    let before_lengths = self.buffer_lengths.clone();
                    let mut continuing: Option<Vec<OwnerState>> = None;
                    let mut continuing_lengths: Option<Vec<Option<u64>>> = None;
                    for arm in arms {
                        self.state.clone_from(&before);
                        self.buffer_lengths.clone_from(&before_lengths);
                        self.matrix_shapes.fill(None);
                        let active_start = self.active.len();
                        for binding in &arm.bindings {
                            if !self.types.guarantees_copy(binding.ty) {
                                self.state[binding.local.0 as usize] = OwnerState::Owned;
                                self.active.push(binding.local);
                            } else if let Some(owner) = borrowed_owner {
                                self.provenance[binding.local.0 as usize] = Some(owner);
                            }
                        }
                        if let Some(owner) = borrowed_owner {
                            self.borrowed.last_mut().unwrap().insert(owner);
                        }
                        self.block(&mut arm.body, true)?;
                        if !definitely_returns(&arm.body) {
                            for binding in arm.bindings.iter().rev() {
                                if !self.types.needs_drop(binding.ty) {
                                    continue;
                                }
                                let state = self.state[binding.local.0 as usize];
                                match state {
                                    OwnerState::Owned => arm
                                        .body
                                        .exit_drops
                                        .push(HirDrop::Unconditional(binding.local)),
                                    OwnerState::MaybeMoved => arm
                                        .body
                                        .exit_drops
                                        .push(HirDrop::Conditional(binding.local)),
                                    _ => continue,
                                }
                                self.state[binding.local.0 as usize] = OwnerState::Dropped;
                            }
                        }
                        if let Some(owner) = borrowed_owner {
                            self.borrowed.last_mut().unwrap().remove(&owner);
                        }
                        self.active.truncate(active_start);
                        if !definitely_returns(&arm.body) {
                            if let Some(previous) = &mut continuing {
                                for local in &self.active {
                                    let index = local.0 as usize;
                                    previous[index] =
                                        merge_owner_state(previous[index], self.state[index]);
                                }
                                if let Some(previous_lengths) = &mut continuing_lengths {
                                    for local in &self.active {
                                        let index = local.0 as usize;
                                        if previous_lengths[index] != self.buffer_lengths[index] {
                                            previous_lengths[index] = None;
                                        }
                                    }
                                }
                            } else {
                                continuing = Some(self.state.clone());
                                continuing_lengths = Some(self.buffer_lengths.clone());
                            }
                        }
                    }
                    self.state = continuing.unwrap_or(before);
                    self.buffer_lengths = continuing_lengths.unwrap_or(before_lengths);
                    self.matrix_shapes.fill(None);
                }
            }
        }
        block.exit_drops.clear();
        if !definitely_returns(block) {
            for local in self.active[active_start..].iter().rev().copied() {
                if self.types.needs_drop(self.locals[local.0 as usize].ty) {
                    match self.state[local.0 as usize] {
                        OwnerState::Owned => block.exit_drops.push(HirDrop::Unconditional(local)),
                        OwnerState::MaybeMoved => {
                            block.exit_drops.push(HirDrop::Conditional(local))
                        }
                        _ => continue,
                    }
                    self.state[local.0 as usize] = OwnerState::Dropped;
                }
            }
        }
        self.active.truncate(active_start);
        self.borrowed.pop();
        self.storage_borrowed.pop();
        self.storage_ranges.pop();
        self.iteration_element_borrowed.pop();
        if !nested {
            debug_assert!(self.borrowed.is_empty());
            debug_assert!(self.storage_borrowed.is_empty());
            debug_assert!(self.iteration_element_borrowed.is_empty());
        }
        Ok(())
    }

    fn expr(&mut self, expr: &HirExpr) -> Result<(), Vec<Diagnostic>> {
        match &expr.kind {
            HirExprKind::Class(op) => {
                for operand in op.operands() {
                    self.expr(operand)?;
                }
                Ok(())
            }
            HirExprKind::String(op) => {
                for operand in op.operands() {
                    self.expr(operand)?;
                }
                Ok(())
            }
            HirExprKind::Text { op, .. } => {
                for operand in op.operands() {
                    self.expr(operand)?;
                }
                Ok(())
            }
            HirExprKind::Core(op) => {
                for operand in op.operands() {
                    self.expr(operand)?;
                }
                Ok(())
            }
            HirExprKind::CallScopedSharedBorrow { source, .. } => match source {
                CallBorrowSource::Place(place) => self.place(place, expr.span),
                CallBorrowSource::Temporary(initializer) => self.expr(initializer),
            },
            HirExprKind::Move(local) => self.move_local(*local, expr.span),
            HirExprKind::Local(local) => {
                if self.types.guarantees_copy(expr.ty) {
                    Ok(())
                } else {
                    self.require_owned(*local, expr.span)
                }
            }
            HirExprKind::Unit
            | HirExprKind::Int(_)
            | HirExprKind::Float(_)
            | HirExprKind::Bool(_)
            | HirExprKind::NullableNull { .. }
            | HirExprKind::FunctionRef { .. }
            | HirExprKind::AlgebraicValue { .. } => Ok(()),
            HirExprKind::NullableInject { payload, .. }
            | HirExprKind::NullableIsNull { operand: payload }
            | HirExprKind::LogicalNot { operand: payload } => self.expr(payload),
            HirExprKind::MatrixAxisVectorView {
                source,
                fixed_index,
                axis,
                ..
            } => {
                self.place(source, expr.span)?;
                let owner = self.owner_of_place(source);
                self.borrowed.push(owner.into_iter().collect());
                self.storage_borrowed.push(owner.into_iter().collect());
                self.storage_ranges
                    .push(owner.into_iter().map(|o| (o, None)).collect());
                self.expr(fixed_index)?;
                self.borrowed.pop();
                self.storage_borrowed.pop();
                self.storage_ranges.pop();
                if let Some(owner) = owner
                    && !self.types.guarantees_copy(self.locals[owner.0 as usize].ty)
                {
                    self.require_owned(owner, expr.span)?;
                }
                let shape = if let HirPlaceBase::Local(local) = source.base
                    && source.projections.is_empty()
                {
                    self.matrix_shapes[local.0 as usize]
                } else {
                    None
                };
                let extent = shape.map(|(r, c)| {
                    if *axis == crate::types::Orientation::Row {
                        r
                    } else {
                        c
                    }
                });
                if let HirExprKind::Int(i) = fixed_index.kind
                    && (i == 0 || extent.is_some_and(|n| i > i128::from(n)))
                {
                    return Err(self.error("E0296", format!("IndexOutOfBounds: Matrix {axis:?} projection index {i}, extent {extent:?}"), fixed_index.span));
                }
                Ok(())
            }
            HirExprKind::ListSwapRemove { source, index, .. } => {
                self.place(source, expr.span)?;
                self.expr(index)?;
                if let Some(owner) = self.owner_of_place(source) {
                    let direct = source.projections.is_empty();
                    let tail = self.buffer_lengths[owner.0 as usize].and_then(|n| n.checked_sub(1));
                    let removed = match index.kind {
                        HirExprKind::Int(i) => u64::try_from(i).ok(),
                        _ => None,
                    };
                    if self
                        .storage_ranges
                        .iter()
                        .flatten()
                        .any(|(root, borrowed)| {
                            *root == owner
                                && !(direct
                                    && borrowed
                                        .zip(tail)
                                        .zip(removed)
                                        .is_some_and(|((i, t), r)| i < t && i != r))
                        })
                    {
                        return Err(self.error("E0321", "swap_remove invalidates a live reference/view to the removed slot or old tail, or an unknown/maybe affected index or whole-list range", expr.span));
                    }
                    self.buffer_lengths[owner.0 as usize] = if direct { tail } else { None };
                }
                Ok(())
            }
            HirExprKind::ListRemove { source, index, .. } => {
                self.place(source, expr.span)?;
                self.expr(index)?;
                if let Some(owner) = self.owner_of_place(source) {
                    let direct = source.projections.is_empty();
                    let tail = self.buffer_lengths[owner.0 as usize].and_then(|n| n.checked_sub(1));
                    let removed = match index.kind {
                        HirExprKind::Int(i) => u64::try_from(i).ok(),
                        _ => None,
                    };
                    if self
                        .storage_ranges
                        .iter()
                        .flatten()
                        .any(|(root, borrowed)| {
                            *root == owner
                                && !(direct && borrowed.zip(removed).is_some_and(|(i, r)| i < r))
                        })
                    {
                        return Err(self.error("E0323", "remove invalidates a live reference/view in the affected suffix, or an unknown index relation or whole-list range", expr.span));
                    }
                    self.buffer_lengths[owner.0 as usize] = if direct { tail } else { None };
                }
                Ok(())
            }
            HirExprKind::ListPop { source, .. } => {
                self.place(source, expr.span)?;
                if let Some(owner) = self.owner_of_place(source) {
                    // Only a direct root and a direct constant element borrow have
                    // enough provenance to prove survival. Nested storage fails closed.
                    let direct = source.projections.is_empty();
                    let tail = self.buffer_lengths[owner.0 as usize].and_then(|n| n.checked_sub(1));
                    if self.storage_ranges.iter().flatten().any(|(root, index)| {
                        *root == owner && !(direct && index.zip(tail).is_some_and(|(i, t)| i < t))
                    }) {
                        return Err(self.error("E0319", "pop invalidates a live reference/view that may cover the removed tail (including an unknown index or whole-list range)", expr.span));
                    }
                    self.buffer_lengths[owner.0 as usize] = if direct { tail } else { None };
                }
                Ok(())
            }
            HirExprKind::Load(place)
            | HirExprKind::Borrow { place, .. }
            | HirExprKind::View { source: place, .. }
            | HirExprKind::VectorView { source: place, .. }
            | HirExprKind::MatrixView { source: place, .. } => self.place(place, expr.span),
            HirExprKind::BufferInit {
                length, initial, ..
            }
            | HirExprKind::ArrayFill {
                length, initial, ..
            } => {
                self.expr(length)?;
                self.expr(initial)
            }
            HirExprKind::MatrixInit { elements, .. }
            | HirExprKind::VectorInit { elements, .. }
            | HirExprKind::ArrayInit { elements, .. }
            | HirExprKind::ListInit { elements, .. } => {
                for element in elements {
                    self.expr(element)?;
                }
                Ok(())
            }
            HirExprKind::NullablePayload { source, .. }
            | HirExprKind::MatrixRows { source }
            | HirExprKind::MatrixColumns { source }
            | HirExprKind::VectorDimension { source }
            | HirExprKind::ArrayLength { source }
            | HirExprKind::ListLength { source }
            | HirExprKind::ListCapacity { source } => self.place(source, expr.span),
            HirExprKind::Call { args, .. } => self.call_arguments(
                &args
                    .iter()
                    .map(|argument| (&argument.initializer, Some(argument.binding)))
                    .collect::<Vec<_>>(),
            ),
            HirExprKind::IndirectCall { callee, args, .. } => {
                self.expr(callee)?;
                self.call_arguments(
                    &args
                        .iter()
                        .map(|argument| (argument, None))
                        .collect::<Vec<_>>(),
                )
            }
            HirExprKind::StructInit { fields, .. } => {
                for (_, value) in fields {
                    self.expr(value)?;
                }
                Ok(())
            }
            HirExprKind::EnumInit { payloads, .. } => {
                for value in payloads {
                    self.expr(value)?;
                }
                Ok(())
            }
            HirExprKind::VectorTranspose { operand, .. }
            | HirExprKind::Coerce { operand, .. }
            | HirExprKind::ExplicitCast { operand, .. }
            | HirExprKind::Unary { operand, .. } => self.expr(operand),
            HirExprKind::AlgebraicProduct {
                left,
                right,
                product,
                ..
            } => {
                self.expr(left)?;
                let owner = self.derived_owner(left);
                self.borrowed.push(owner.into_iter().collect());
                self.storage_borrowed.push(owner.into_iter().collect());
                self.storage_ranges
                    .push(owner.into_iter().map(|o| (o, None)).collect());
                self.expr(right)?;
                self.borrowed.pop();
                self.storage_borrowed.pop();
                self.storage_ranges.pop();
                if matches!(product, AlgebraicProductKind::MatrixMatrix { .. }) {
                    if let Some(((_, a), (b, _))) = self
                        .known_matrix_shape(left)
                        .zip(self.known_matrix_shape(right))
                        .filter(|((_, a), (b, _))| a != b)
                    {
                        return Err(self.error("E0345", format!("ShapeMismatch for algebraic multiplication: contraction dimension {a} versus {b}"), expr.span));
                    }
                }
                if let AlgebraicProductKind::MatrixVector { matrix_side, .. } = product {
                    let dimensions = if *matrix_side == ScalarSide::Left {
                        self.known_matrix_shape(left)
                            .map(|(_, c)| c)
                            .zip(self.known_length(right))
                    } else {
                        self.known_length(left)
                            .zip(self.known_matrix_shape(right).map(|(r, _)| r))
                    };
                    if let Some((a, b)) = dimensions.filter(|(a, b)| a != b) {
                        return Err(self.error("E0345", format!("ShapeMismatch for algebraic multiplication: contraction dimension {a} versus {b}"), expr.span));
                    }
                }
                if matches!(product, AlgebraicProductKind::Inner { .. }) {
                    if let Some((a, b)) = self
                        .known_length(left)
                        .zip(self.known_length(right))
                        .filter(|(a, b)| a != b)
                    {
                        return Err(self.error("E0345", format!("ShapeMismatch for algebraic multiplication: dimension {a} versus {b}"), expr.span));
                    }
                }
                Ok(())
            }
            HirExprKind::VectorScalarMultiply { left, right, .. }
            | HirExprKind::MatrixScalarMultiply { left, right, .. } => {
                self.expr(left)?;
                let owner = self.derived_owner(left);
                self.borrowed.push(owner.into_iter().collect());
                self.storage_borrowed.push(owner.into_iter().collect());
                self.storage_ranges
                    .push(owner.into_iter().map(|o| (o, None)).collect());
                self.expr(right)?;
                self.borrowed.pop();
                self.storage_borrowed.pop();
                self.storage_ranges.pop();
                Ok(())
            }
            HirExprKind::VectorElementwiseBinary {
                left,
                right,
                source_op,
                ..
            }
            | HirExprKind::MatrixElementwiseBinary {
                left,
                right,
                source_op,
                ..
            } => {
                self.expr(left)?;
                let owner = self.derived_owner(left);
                self.borrowed.push(owner.into_iter().collect());
                self.storage_borrowed.push(owner.into_iter().collect());
                self.storage_ranges
                    .push(owner.into_iter().map(|o| (o, None)).collect());
                self.expr(right)?;
                self.borrowed.pop();
                self.storage_borrowed.pop();
                self.storage_ranges.pop();
                let mismatch = if self.types.vector_like_info(left.ty).is_some() {
                    self.known_length(left)
                        .zip(self.known_length(right))
                        .filter(|(a, b)| a != b)
                        .map(|(a, b)| format!("dimension {a} versus {b}"))
                } else {
                    self.known_matrix_shape(left)
                        .zip(self.known_matrix_shape(right))
                        .filter(|(a, b)| a != b)
                        .map(|(a, b)| format!("shape {a:?} versus {b:?}"))
                };
                if let Some(shape) = mismatch {
                    return Err(self.error(
                        "E0345",
                        format!(
                            "ShapeMismatch for {}: {shape}",
                            if *source_op == AstBinaryOp::Add {
                                "+"
                            } else {
                                "-"
                            }
                        ),
                        expr.span,
                    ));
                }
                Ok(())
            }
            HirExprKind::ShortCircuitAnd { left, right }
            | HirExprKind::ShortCircuitOr { left, right }
            | HirExprKind::CapabilityBinary { left, right, .. }
            | HirExprKind::Binary { left, right, .. } => {
                self.expr(left)?;
                self.expr(right)
            }
        }
    }

    fn place(&mut self, place: &HirPlace, span: Span) -> Result<(), Vec<Diagnostic>> {
        if let Some(owner) = self.owner_of_place(place) {
            if !self.types.guarantees_copy(self.locals[owner.0 as usize].ty) {
                self.require_owned(owner, span)?;
            }
        }
        if let HirPlaceBase::Dereference { reference, .. } = &place.base {
            self.expr(reference)?;
        }
        for (position, projection) in place.projections.iter().enumerate() {
            if let HirPlaceProjection::Index {
                index,
                column,
                semantics,
                ..
            } = projection
            {
                self.expr(index)?;
                if let Some(column) = column {
                    self.expr(column)?;
                    let shape = match place.base {
                        HirPlaceBase::Local(local) if position == 0 => {
                            self.matrix_shapes[local.0 as usize]
                        }
                        _ => None,
                    };
                    for (axis, expr, extent) in [
                        ("row", index.as_ref(), shape.map(|s| s.0)),
                        ("column", column.as_ref(), shape.map(|s| s.1)),
                    ] {
                        if let HirExprKind::Int(value) = expr.kind
                            && (value == 0 || extent.is_some_and(|n| value > i128::from(n)))
                        {
                            return Err(self.error("E0296", format!("IndexOutOfBounds: constant Matrix {axis} {value}, extent {extent:?}"), expr.span));
                        }
                    }
                }
                if let HirExprKind::Int(value) = index.kind
                    && let HirPlaceBase::Local(local) = place.base
                    && position == 0
                    && let Some(length) = self.buffer_lengths[local.0 as usize]
                    && u64::try_from(value).is_ok_and(|index| !semantics.contains(index, length))
                {
                    return Err(self.error(
                        "E0296",
                        format!("constant index {value} is out of bounds for {semantics:?} extent {length}"),
                        index.span,
                    ));
                }
            }
        }
        if let Some(owner) = self.owner_of_place(place)
            && !self.types.guarantees_copy(self.locals[owner.0 as usize].ty)
        {
            self.require_owned(owner, span)?;
        }
        Ok(())
    }

    fn call_arguments(
        &mut self,
        args: &[(&HirExpr, Option<LocalId>)],
    ) -> Result<(), Vec<Diagnostic>> {
        if let Some(argument) = args
            .iter()
            .map(|(argument, _)| *argument)
            .find(|argument| self.types.has_untracked_mutable_view_effect(argument.ty))
        {
            return Err(self.error("E0313", "passing a mutable mathematical view containing List storage requires nested alias-effect provenance", argument.span));
        }
        if args.iter().any(|(argument, _)| {
            self.types
                .reference_info(argument.ty)
                .is_some_and(|(_, mutable)| mutable)
        }) {
            self.matrix_shapes.fill(None);
        }
        self.borrowed.push(BTreeSet::new());
        self.storage_borrowed.push(BTreeSet::new());
        self.storage_ranges.push(Vec::new());
        for (argument, binding) in args {
            self.expr(argument)?;
            if let Some(binding) = binding {
                if let Some(owner) = self.derived_owner(argument) {
                    self.provenance[binding.0 as usize] = Some(owner);
                }
                if !self.types.guarantees_copy(argument.ty) {
                    self.buffer_lengths[binding.0 as usize] = self.known_length(argument);
                    self.matrix_shapes[binding.0 as usize] = self.known_matrix_shape(argument);
                    self.state[binding.0 as usize] = OwnerState::Owned;
                    self.active.push(*binding);
                }
            }
            if self
                .types
                .reference_info(argument.ty)
                .is_some_and(|(_, mutable)| mutable)
                && let Some(owner) = self.derived_owner(argument)
                && self
                    .iteration_element_borrowed
                    .iter()
                    .any(|scope| scope.contains(&owner))
            {
                return Err(self.error(
                    "E0446",
                    "writable call argument may replace or invalidate the current borrowed iteration element",
                    argument.span,
                ));
            }
            if self
                .types
                .reference_info(argument.ty)
                .is_some_and(|(pointee, mutable)| mutable && self.types.may_contain_list(pointee))
                && let Some(owner) = self.derived_owner(argument).or_else(|| {
                    if let HirExprKind::Borrow { place, .. } = &argument.kind {
                        self.owner_of_place(place)
                    } else {
                        None
                    }
                })
                && self.has_live_storage_borrow(owner)
            {
                return Err(self.error(
                    "E0313",
                    "cannot pass a writable reference to a call while a derived element reference/view remains live",
                    argument.span,
                ));
            }
            if self
                .types
                .reference_info(argument.ty)
                .is_some_and(|(pointee, mutable)| mutable && self.types.may_contain_list(pointee))
                && let Some(owner) = self.derived_owner(argument)
            {
                self.buffer_lengths[owner.0 as usize] = None;
            }
            if let Some(owner) = self.derived_owner(argument) {
                self.borrowed.last_mut().unwrap().insert(owner);
                if self.is_list_storage_borrow(argument) {
                    let index = self.storage_index(argument);
                    self.storage_borrowed.last_mut().unwrap().insert(owner);
                    self.storage_ranges.last_mut().unwrap().push((owner, index));
                }
            }
        }
        for (argument, _) in args {
            if self
                .types
                .reference_info(argument.ty)
                .is_some_and(|(pointee, mutable)| mutable && self.types.may_contain_list(pointee))
                && let Some(owner) = self.derived_owner(argument)
                && self.has_live_storage_borrow(owner)
            {
                return Err(self.error("E0313", "writable call argument may invalidate another live element reference/view argument", argument.span));
            }
        }
        self.borrowed.pop();
        self.storage_borrowed.pop();
        self.storage_ranges.pop();
        for (_, binding) in args {
            if let Some(binding) = binding
                && !self
                    .types
                    .guarantees_copy(self.locals[binding.0 as usize].ty)
            {
                self.move_local(*binding, self.locals[binding.0 as usize].span)?;
            }
        }
        Ok(())
    }

    fn owner_of_place(&self, place: &HirPlace) -> Option<LocalId> {
        match &place.base {
            HirPlaceBase::Local(local) => {
                if self.types.guarantees_copy(self.locals[local.0 as usize].ty) {
                    self.provenance[local.0 as usize]
                } else {
                    Some(*local)
                }
            }
            HirPlaceBase::Dereference { reference, .. } => self.derived_owner(reference).or({
                if let HirExprKind::Local(local) = reference.kind {
                    Some(local)
                } else {
                    None
                }
            }),
        }
    }

    fn derived_owner(&self, expr: &HirExpr) -> Option<LocalId> {
        match &expr.kind {
            HirExprKind::Borrow { place, .. }
            | HirExprKind::View { source: place, .. }
            | HirExprKind::MatrixAxisVectorView { source: place, .. }
            | HirExprKind::VectorView { source: place, .. }
            | HirExprKind::MatrixView { source: place, .. }
            | HirExprKind::CallScopedSharedBorrow {
                source: CallBorrowSource::Place(place),
                ..
            } => self.owner_of_place(place),
            HirExprKind::Load(place) if self.types.mathematical_view_info(expr.ty).is_some() => {
                self.owner_of_place(place)
            }
            HirExprKind::Local(local) => self.provenance[local.0 as usize],
            _ => None,
        }
    }

    fn local_root(&self, place: &HirPlace) -> Option<LocalId> {
        self.owner_of_place(place)
    }

    fn structural_mutation(&mut self, place: &HirPlace, span: Span) -> Result<(), Vec<Diagnostic>> {
        self.place(place, span)?;
        if let Some(owner) = self.owner_of_place(place)
            && self.has_live_storage_borrow(owner)
        {
            return Err(self.error(
                "E0313",
                "cannot structurally mutate List storage while a derived element reference/view remains live",
                span,
            ));
        }
        Ok(())
    }

    fn storage_index(&self, expr: &HirExpr) -> Option<u64> {
        match &expr.kind {
            HirExprKind::Local(local) => self.borrow_indices[local.0 as usize],
            HirExprKind::Borrow { place, .. }
            | HirExprKind::CallScopedSharedBorrow {
                source: CallBorrowSource::Place(place),
                ..
            } => {
                if let HirPlaceBase::Local(local) = place.base
                    && self
                        .types
                        .list_element(self.locals[local.0 as usize].ty)
                        .is_some()
                    && let [
                        HirPlaceProjection::Index {
                            index,
                            column: None,
                            ..
                        },
                    ] = place.projections.as_slice()
                    && let HirExprKind::Int(index) = index.kind
                {
                    u64::try_from(index).ok()
                } else {
                    None
                }
            }
            _ => None,
        }
    }

    fn is_list_storage_borrow(&self, expr: &HirExpr) -> bool {
        match &expr.kind {
            HirExprKind::Borrow { place, .. }
            | HirExprKind::CallScopedSharedBorrow {
                source: CallBorrowSource::Place(place),
                ..
            } => place
                .projections
                .iter()
                .any(|projection| matches!(projection, HirPlaceProjection::Index { .. })),
            HirExprKind::MatrixAxisVectorView { .. }
            | HirExprKind::VectorView { .. }
            | HirExprKind::MatrixView { .. } => true,
            HirExprKind::Load(_) if self.types.mathematical_view_info(expr.ty).is_some() => true,
            HirExprKind::View { source, .. } => self.types.list_element(source.ty).is_some(),
            HirExprKind::Local(local) => self.storage_references[local.0 as usize],
            _ => false,
        }
    }

    fn known_matrix_shape(&self, expr: &HirExpr) -> Option<(u64, u64)> {
        match &expr.kind {
            HirExprKind::AlgebraicProduct {
                left,
                right,
                product: AlgebraicProductKind::MatrixMatrix { .. },
                ..
            } => self
                .known_matrix_shape(left)
                .zip(self.known_matrix_shape(right))
                .map(|((r, _), (_, c))| (r, c)),
            HirExprKind::AlgebraicProduct {
                left,
                right,
                product: AlgebraicProductKind::Outer { .. },
                ..
            } => self.known_length(left).zip(self.known_length(right)),
            HirExprKind::MatrixScalarMultiply {
                left,
                right,
                scalar_side,
                ..
            } => self.known_matrix_shape(if *scalar_side == ScalarSide::Left {
                right
            } else {
                left
            }),
            HirExprKind::MatrixElementwiseBinary { left, .. } => self.known_matrix_shape(left),
            HirExprKind::MatrixInit { rows, columns, .. } => Some((*rows, *columns)),
            HirExprKind::MatrixView {
                source, transpose, ..
            } => {
                if let HirPlaceBase::Local(local) = source.base
                    && source.projections.is_empty()
                {
                    self.matrix_shapes[local.0 as usize]
                        .map(|(r, c)| if *transpose { (c, r) } else { (r, c) })
                } else {
                    None
                }
            }
            HirExprKind::Move(local) | HirExprKind::Local(local) => {
                self.matrix_shapes[local.0 as usize]
            }
            _ => None,
        }
    }

    fn known_length(&self, expr: &HirExpr) -> Option<u64> {
        match &expr.kind {
            HirExprKind::AlgebraicProduct {
                left,
                right,
                product: AlgebraicProductKind::MatrixVector { matrix_side, .. },
                ..
            } => {
                if *matrix_side == ScalarSide::Left {
                    self.known_matrix_shape(left).map(|(r, _)| r)
                } else {
                    self.known_matrix_shape(right).map(|(_, c)| c)
                }
            }

            HirExprKind::VectorScalarMultiply {
                left,
                right,
                scalar_side,
                ..
            } => self.known_length(if *scalar_side == ScalarSide::Left {
                right
            } else {
                left
            }),
            HirExprKind::VectorElementwiseBinary { left, .. } => self.known_length(left),
            HirExprKind::MatrixAxisVectorView { source, axis, .. } => {
                if let HirPlaceBase::Local(local) = source.base
                    && source.projections.is_empty()
                {
                    self.matrix_shapes[local.0 as usize].map(|(r, c)| {
                        if *axis == crate::types::Orientation::Row {
                            c
                        } else {
                            r
                        }
                    })
                } else {
                    None
                }
            }
            HirExprKind::VectorTranspose { operand, .. } => self.known_length(operand),
            HirExprKind::VectorView { source, .. } => {
                if let HirPlaceBase::Local(local) = source.base
                    && source.projections.is_empty()
                {
                    self.buffer_lengths[local.0 as usize]
                } else {
                    None
                }
            }
            HirExprKind::BufferInit { length, .. } | HirExprKind::ArrayFill { length, .. } => {
                match length.kind {
                    HirExprKind::Int(value) => u64::try_from(value).ok(),
                    _ => None,
                }
            }
            HirExprKind::VectorInit { elements, .. } => {
                Some(u64::try_from(elements.len()).expect("Vector literal length fits u64"))
            }
            HirExprKind::ArrayInit { elements, .. } => {
                Some(u64::try_from(elements.len()).expect("Array literal length fits u64"))
            }
            HirExprKind::ListInit { elements, .. } => {
                Some(u64::try_from(elements.len()).expect("List literal length fits u64"))
            }
            HirExprKind::Move(local) | HirExprKind::Local(local) => {
                self.buffer_lengths[local.0 as usize]
            }
            HirExprKind::View { source, .. } => match source.base {
                HirPlaceBase::Local(local) => self.buffer_lengths[local.0 as usize],
                HirPlaceBase::Dereference { .. } => None,
            },
            _ => None,
        }
    }
}

fn merge_owner_state(left: OwnerState, right: OwnerState) -> OwnerState {
    use OwnerState::{Dropped, MaybeMoved, Moved, Owned, Uninitialized};
    match (left, right) {
        (Uninitialized, Uninitialized) => Uninitialized,
        (Owned, Owned) => Owned,
        (Moved | Dropped, Moved | Uninitialized)
        | (Moved, Dropped)
        | (Uninitialized, Moved | Dropped) => Moved,
        (Dropped, Dropped) => Dropped,
        (MaybeMoved, _)
        | (_, MaybeMoved)
        | (Owned, Moved | Dropped | Uninitialized)
        | (Moved | Dropped | Uninitialized, Owned) => MaybeMoved,
    }
}

struct Analyzer<'a> {
    scopes: Vec<BTreeMap<String, LocalId>>,
    locals: Vec<HirLocal>,
    signatures: &'a [FunctionSignature],
    names: &'a [BTreeMap<String, FunctionId>],
    imports: &'a [BTreeMap<String, ModuleId>],
    import_bindings: &'a [BTreeSet<String>],
    used_modules: BTreeSet<ModuleId>,
    module_names: &'a BTreeMap<String, ModuleId>,
    aliases: &'a [BTreeMap<String, TypeId>],
    types: &'a mut TypeArena,
    structs: &'a [StructInfo],
    enums: &'a [EnumInfo],
    struct_names: &'a [BTreeMap<String, StructId>],
    enum_names: &'a [BTreeMap<String, EnumId>],
    variant_names: &'a [BTreeMap<String, VariantId>],
    field_names: &'a [BTreeMap<String, FieldId>],
    generic_scope: BTreeMap<String, TypeId>,
    struct_arities: &'a [usize],
    enum_arities: &'a [usize],
    module: ModuleId,
    return_type: TypeId,
    target: TargetProperties,
    class_method: Option<(ClassId, crate::ClassMethodInfo)>,
    initialized_fields: BTreeSet<FieldId>,
    active_catches: Vec<CatchId>,
    next_catch: u32,
    loop_depth: usize,
    inside_finally: usize,
    next_finally: u32,
    next_loop: u32,
    next_call_site: u32,
    default_forbidden: Option<(String, BTreeMap<String, bool>)>,
    null_states: BTreeMap<LocalId, NullState>,
    next_non_null_proof: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum IntrinsicGenericConstructor {
    Buffer,
    Array,
    Matrix,
    Vector,
    List,
    View,
    ViewMut,
    VectorView,
    VectorViewMut,
    MatrixView,
    MatrixViewMut,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum GenericFamilyKey {
    Struct(StructId),
    Enum(EnumId),
    Intrinsic(IntrinsicGenericConstructor),
}

#[derive(Clone, Debug)]
struct LocalTypePattern {
    family: GenericFamilyKey,
    nullable: bool,
    source_name: String,
    source_span: Span,
    expected_arity: usize,
}

enum LocalTypeExpectation {
    Exact(TypeId),
    InferRoot(LocalTypePattern),
}

#[derive(Clone)]
struct Checked {
    expr: HirExpr,
    constant: Option<ConstantValue>,
}
#[derive(Clone, Copy)]
enum ConstantValue {
    Integer(i128),
    Float(FloatValue),
}
impl Analyzer<'_> {
    fn intrinsic_generic_constructor(name: &str) -> Option<IntrinsicGenericConstructor> {
        match name {
            "Buffer" => Some(IntrinsicGenericConstructor::Buffer),
            "Array" => Some(IntrinsicGenericConstructor::Array),
            "Matrix" => Some(IntrinsicGenericConstructor::Matrix),
            "Vector" => Some(IntrinsicGenericConstructor::Vector),
            "List" => Some(IntrinsicGenericConstructor::List),
            "View" => Some(IntrinsicGenericConstructor::View),
            "ViewMut" => Some(IntrinsicGenericConstructor::ViewMut),
            "VectorView" => Some(IntrinsicGenericConstructor::VectorView),
            "VectorViewMut" => Some(IntrinsicGenericConstructor::VectorViewMut),
            "MatrixView" => Some(IntrinsicGenericConstructor::MatrixView),
            "MatrixViewMut" => Some(IntrinsicGenericConstructor::MatrixViewMut),
            _ => None,
        }
    }

    fn omitted_generic_family(&self, ty: &AstType) -> Option<(GenericFamilyKey, usize, String)> {
        let (namespace, name, arguments) = ty.named()?;
        if !arguments.is_empty() {
            return None;
        }
        if namespace.is_none() && self.generic_scope.contains_key(name) {
            return None;
        }
        if namespace.is_none()
            && let Some(constructor) = Self::intrinsic_generic_constructor(name)
        {
            return Some((
                GenericFamilyKey::Intrinsic(constructor),
                intrinsic_type_arity(name).expect("intrinsic constructor has arity"),
                name.into(),
            ));
        }
        let target = namespace.map_or(Some(self.module), |namespace| {
            self.imports[self.module.0 as usize].get(namespace).copied()
        })?;
        if let Some(id) = self.struct_names[target.0 as usize].get(name).copied() {
            let arity = self.struct_arities[id.0 as usize];
            return (arity > 0).then(|| (GenericFamilyKey::Struct(id), arity, name.into()));
        }
        if let Some(id) = self.enum_names[target.0 as usize].get(name).copied() {
            let arity = self.enum_arities[id.0 as usize];
            return (arity > 0).then(|| (GenericFamilyKey::Enum(id), arity, name.into()));
        }
        None
    }

    fn contains_nested_generic_omission(&self, ty: &AstType) -> bool {
        match &ty.kind {
            crate::AstTypeKind::Named { arguments, .. } => {
                self.omitted_generic_family(ty).is_some()
                    || arguments
                        .iter()
                        .any(|argument| self.contains_nested_generic_omission(argument))
            }
            crate::AstTypeKind::Reference(reference) => {
                self.contains_nested_generic_omission(&reference.pointee)
            }
            crate::AstTypeKind::Function { parameters, result } => {
                parameters
                    .iter()
                    .any(|parameter| self.contains_nested_generic_omission(parameter))
                    || self.contains_nested_generic_omission(result)
            }
            crate::AstTypeKind::Nullable { payload, .. } => {
                self.contains_nested_generic_omission(payload)
            }
        }
    }

    fn resolve_local_type_expectation(
        &mut self,
        ty: &AstType,
    ) -> Result<LocalTypeExpectation, Vec<Diagnostic>> {
        let arity_diagnostics = match self.resolve_source_type(ty) {
            Ok(exact) => return Ok(LocalTypeExpectation::Exact(exact)),
            Err(diagnostics)
                if diagnostics
                    .first()
                    .is_none_or(|diagnostic| diagnostic.code != "E0261") =>
            {
                return Err(diagnostics);
            }
            Err(diagnostics) => diagnostics,
        };

        let candidate = match &ty.kind {
            crate::AstTypeKind::Named { .. } => {
                self.omitted_generic_family(ty)
                    .map(|(family, expected_arity, source_name)| {
                        (family, expected_arity, source_name, false, ty.span)
                    })
            }
            crate::AstTypeKind::Nullable { payload, .. } => self
                .omitted_generic_family(payload)
                .map(|(family, expected_arity, source_name)| {
                    (family, expected_arity, source_name, true, payload.span)
                }),
            _ => None,
        };
        if let Some((family, expected_arity, source_name, nullable, source_span)) = candidate {
            let family_type = match &ty.kind {
                crate::AstTypeKind::Nullable { payload, .. } => payload.as_ref(),
                _ => ty,
            };
            if let Some((Some(namespace), _, _)) = family_type.named()
                && let Some(module) = self.imports[self.module.0 as usize].get(namespace)
            {
                self.used_modules.insert(*module);
            }
            return Ok(LocalTypeExpectation::InferRoot(LocalTypePattern {
                family,
                nullable,
                source_name,
                source_span,
                expected_arity,
            }));
        }
        if self.contains_nested_generic_omission(ty) {
            return Err(vec![Diagnostic::new(
                "E0463",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "generic arguments may be omitted only for the root local constructor (optionally nullable)",
                Some(ty.span),
            )]);
        }
        Err(arity_diagnostics)
    }

    fn rhs_generic_family(&self, ty: TypeId) -> Option<(GenericFamilyKey, usize)> {
        match self.types.get(ty).copied()? {
            TypeData::StructInstance(id, arguments) => Some((
                GenericFamilyKey::Struct(id),
                self.types.arguments(arguments)?.len(),
            )),
            TypeData::EnumInstance(id, arguments) => Some((
                GenericFamilyKey::Enum(id),
                self.types.arguments(arguments)?.len(),
            )),
            TypeData::Buffer { .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::Buffer),
                1,
            )),
            TypeData::Array { .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::Array),
                1,
            )),
            TypeData::Matrix { .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::Matrix),
                1,
            )),
            TypeData::Vector { .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::Vector),
                2,
            )),
            TypeData::List { .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::List),
                1,
            )),
            TypeData::View { mutable: false, .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::View),
                1,
            )),
            TypeData::View { mutable: true, .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::ViewMut),
                1,
            )),
            TypeData::VectorView { mutable: false, .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::VectorView),
                2,
            )),
            TypeData::VectorView { mutable: true, .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::VectorViewMut),
                2,
            )),
            TypeData::MatrixView { mutable: false, .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::MatrixView),
                1,
            )),
            TypeData::MatrixView { mutable: true, .. } => Some((
                GenericFamilyKey::Intrinsic(IntrinsicGenericConstructor::MatrixViewMut),
                1,
            )),
            _ => None,
        }
    }

    fn adopt_local_pattern(
        &self,
        pattern: &LocalTypePattern,
        rhs: TypeId,
        initializer_span: Span,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        let rhs_payload = self.types.nullable_payload(rhs);
        if rhs_payload.is_some() != pattern.nullable {
            return Err(vec![Diagnostic::new(
                "E0464",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "initializer type does not have the required local type shape `{}{}`",
                    pattern.source_name,
                    if pattern.nullable { "?<...>" } else { "<...>" }
                ),
                Some(initializer_span),
            )]);
        }
        let application = rhs_payload.unwrap_or(rhs);
        let Some((family, arity)) = self.rhs_generic_family(application) else {
            let malformed_same_family = matches!(
                (pattern.family, self.types.get(application)),
                (GenericFamilyKey::Struct(expected), Some(TypeData::Struct(actual))) if expected == *actual
            ) || matches!(
                (pattern.family, self.types.get(application)),
                (GenericFamilyKey::Enum(expected), Some(TypeData::Enum(actual))) if expected == *actual
            );
            return Err(vec![Diagnostic::new(
                if malformed_same_family {
                    "E0464"
                } else {
                    "E0461"
                },
                Phase::Semantic,
                DiagnosticCategory::Type,
                if malformed_same_family {
                    format!(
                        "initializer type does not have the required local type shape `{}<...>`",
                        pattern.source_name
                    )
                } else {
                    format!(
                        "local type pattern `{}` cannot be inferred from initializer type `{}`",
                        pattern.source_name,
                        self.type_name(rhs)
                    )
                },
                Some(initializer_span),
            )]);
        };
        if family != pattern.family {
            return Err(vec![Diagnostic::new(
                "E0460",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "local type pattern `{}` requires `{}<...>`, but initializer has `{}`",
                    pattern.source_name,
                    pattern.source_name,
                    self.type_name(rhs)
                ),
                Some(pattern.source_span),
            )]);
        }
        if arity != pattern.expected_arity {
            return Err(vec![Diagnostic::new(
                "E0464",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "initializer type does not have the required local type shape `{}<...>`",
                    pattern.source_name
                ),
                Some(initializer_span),
            )]);
        }
        validate_type_constraints(self.types, rhs, self.structs, self.enums, initializer_span)?;
        Ok(rhs)
    }

    fn refine_for_condition(&mut self, condition: &AstExpr, truth: bool) {
        match &condition.kind {
            AstExprKind::Unary {
                op: AstUnaryOp::LogicalNot,
                operand,
            } => {
                self.refine_for_condition(operand, !truth);
            }
            AstExprKind::Binary {
                op: AstBinaryOp::LogicalAnd,
                left,
                right,
            } if truth => {
                self.refine_for_condition(left, true);
                self.refine_for_condition(right, true);
            }
            AstExprKind::Binary {
                op: AstBinaryOp::LogicalOr,
                left,
                right,
            } if !truth => {
                self.refine_for_condition(left, false);
                self.refine_for_condition(right, false);
            }
            AstExprKind::Binary { op, left, right }
                if matches!(op, AstBinaryOp::Equal | AstBinaryOp::NotEqual) =>
            {
                let name = match (&left.kind, &right.kind) {
                    (AstExprKind::Name(name), AstExprKind::Null)
                    | (AstExprKind::Null, AstExprKind::Name(name)) => Some(name),
                    _ => None,
                };
                if let Some(local) = name.and_then(|name| self.lookup(name))
                    && self
                        .types
                        .nullable_payload(self.locals[local.0 as usize].ty)
                        .is_some()
                {
                    let non_null = (*op == AstBinaryOp::NotEqual) == truth;
                    self.null_states.insert(
                        local,
                        if non_null {
                            NullState::NonNull
                        } else {
                            NullState::Null
                        },
                    );
                }
            }
            _ => {}
        }
    }

    fn joined_null_states(
        left: &BTreeMap<LocalId, NullState>,
        right: &BTreeMap<LocalId, NullState>,
    ) -> BTreeMap<LocalId, NullState> {
        left.keys()
            .chain(right.keys())
            .copied()
            .collect::<BTreeSet<_>>()
            .into_iter()
            .map(|local| {
                let l = left.get(&local).copied().unwrap_or(NullState::Unknown);
                let r = right.get(&local).copied().unwrap_or(NullState::Unknown);
                (local, if l == r { l } else { NullState::Unknown })
            })
            .collect()
    }

    fn fresh_non_null_proof(&mut self) -> NonNullProofId {
        let id = NonNullProofId(self.next_non_null_proof);
        self.next_non_null_proof += 1;
        id
    }

    fn invalidate_nullable_aliases_after_mutating_call(&mut self) {
        for local in &self.locals {
            if local.address_taken && self.types.nullable_payload(local.ty).is_some() {
                self.null_states.insert(local.id, NullState::Unknown);
            }
        }
    }

    fn invalid_default_reference(&self, name: &str, span: Span) -> Option<Vec<Diagnostic>> {
        let (parameter, forbidden) = self.default_forbidden.as_ref()?;
        let self_reference = *forbidden.get(name)?;
        Some(vec![Diagnostic::new(
            "E0364",
            Phase::Semantic,
            DiagnosticCategory::Name,
            format!(
                "default for `{parameter}` cannot reference {} parameter `{name}`",
                if self_reference { "itself" } else { "later" }
            ),
            Some(span),
        )])
    }

    fn validate_declared_defaults(
        &mut self,
        signature: &FunctionSignature,
        parameters: &[HirParameter],
    ) -> Result<(), Vec<Diagnostic>> {
        let saved_locals = self.locals.clone();
        let saved_scopes = self.scopes.clone();
        let saved_call_site = self.next_call_site;
        for (index, parameter) in signature.parameters.iter().enumerate() {
            let Some(template) = &parameter.default else {
                continue;
            };
            self.scopes = vec![
                signature.parameters[..index]
                    .iter()
                    .zip(parameters)
                    .map(|(previous, hir)| (previous.name.clone(), hir.local))
                    .collect(),
            ];
            self.default_forbidden = Some((
                parameter.name.clone(),
                signature.parameters[index..]
                    .iter()
                    .enumerate()
                    .map(|(offset, later)| (later.name.clone(), offset == 0))
                    .collect(),
            ));
            let call_site = self.call_site();
            let result = self.adapt_call_argument(
                &template.expression,
                parameter.ty,
                call_site,
                template.parameter_index,
                None,
            );
            if let Err(mut diagnostics) = result {
                self.locals = saved_locals;
                self.scopes = saved_scopes;
                self.next_call_site = saved_call_site;
                self.default_forbidden = None;
                if let Some(diagnostic) = diagnostics.first_mut()
                    && diagnostic.code != "E0364"
                {
                    let cause = diagnostic.message.clone();
                    diagnostic.code = if matches!(
                        diagnostic.category,
                        DiagnosticCategory::Type | DiagnosticCategory::Conversion
                    ) {
                        "E0361"
                    } else {
                        "E0365"
                    };
                    diagnostic.message = format!(
                        "default for parameter `{}` requires {}: {cause}",
                        parameter.name,
                        self.type_name(parameter.ty)
                    );
                }
                return Err(diagnostics);
            }
        }
        self.locals = saved_locals;
        self.scopes = saved_scopes;
        self.next_call_site = saved_call_site;
        self.default_forbidden = None;
        Ok(())
    }
    fn call_site(&mut self) -> CallSiteId {
        let id = CallSiteId(self.next_call_site);
        self.next_call_site = self
            .next_call_site
            .checked_add(1)
            .expect("call site count fits u32");
        id
    }
    fn resolve_source_type(&mut self, ty: &AstType) -> Result<TypeId, Vec<Diagnostic>> {
        let resolved = resolve_type_in_module(
            ty,
            self.module,
            self.aliases,
            self.struct_names,
            self.enum_names,
            self.imports,
            self.module_names,
            self.types,
            &self.generic_scope,
            self.struct_arities,
            self.enum_arities,
        )
        .map_err(|diagnostic| vec![diagnostic])?;
        if let Some((Some(namespace), _, _)) = ty.named()
            && let Some(module) = self.imports[self.module.0 as usize].get(namespace)
        {
            self.used_modules.insert(*module);
        }
        validate_type_constraints(self.types, resolved, self.structs, self.enums, ty.span)?;
        Ok(resolved)
    }

    fn resolve_type_arguments(
        &mut self,
        arguments: &[AstType],
    ) -> Result<Vec<TypeId>, Vec<Diagnostic>> {
        arguments
            .iter()
            .map(|argument| self.resolve_source_type(argument))
            .collect()
    }

    fn nominal_struct_type(
        &mut self,
        id: StructId,
        arguments: Vec<TypeId>,
        span: Span,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        let expected = self.struct_arities[id.0 as usize];
        if arguments.len() != expected {
            return Err(vec![generic_call_arity(
                &self.structs[id.0 as usize].name,
                expected,
                arguments.len(),
                span,
            )]);
        }
        validate_generic_constraints(
            self.types,
            &self.structs[id.0 as usize].generic_parameters,
            &arguments,
            &self.structs[id.0 as usize].name,
            self.structs,
            self.enums,
            span,
            false,
        )?;
        Ok(if expected == 0 {
            self.types
                .id_of(TypeData::Struct(id))
                .expect("interned struct")
        } else {
            self.types.intern_struct_instance(id, arguments)
        })
    }

    fn nominal_enum_type(
        &mut self,
        id: EnumId,
        arguments: Vec<TypeId>,
        span: Span,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        let expected = self.enum_arities[id.0 as usize];
        if arguments.len() != expected {
            return Err(vec![generic_call_arity(
                &self.enums[id.0 as usize].name,
                expected,
                arguments.len(),
                span,
            )]);
        }
        validate_generic_constraints(
            self.types,
            &self.enums[id.0 as usize].generic_parameters,
            &arguments,
            &self.enums[id.0 as usize].name,
            self.structs,
            self.enums,
            span,
            false,
        )?;
        Ok(if expected == 0 {
            self.types.id_of(TypeData::Enum(id)).expect("interned enum")
        } else {
            self.types.intern_enum_instance(id, arguments)
        })
    }

    fn apply_named_type(
        &mut self,
        target: TypeId,
        arguments: &[TypeId],
        span: Span,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        match self.types.get(target).copied() {
            Some(TypeData::Struct(id)) => self.nominal_struct_type(id, arguments.to_vec(), span),
            Some(TypeData::Enum(id)) => self.nominal_enum_type(id, arguments.to_vec(), span),
            _ if arguments.is_empty() => Ok(target),
            _ => Err(vec![generic_call_arity("type", 0, arguments.len(), span)]),
        }
    }

    fn specialize_member_type(
        &mut self,
        aggregate: TypeId,
        member: TypeId,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        let (parameters, arguments) = match self.types.get(aggregate).copied() {
            Some(TypeData::StructInstance(id, args)) => (
                self.structs[id.0 as usize].generic_parameters.clone(),
                self.types
                    .arguments(args)
                    .expect("valid struct arguments")
                    .to_vec(),
            ),
            Some(TypeData::EnumInstance(id, args)) => (
                self.enums[id.0 as usize].generic_parameters.clone(),
                self.types
                    .arguments(args)
                    .expect("valid enum arguments")
                    .to_vec(),
            ),
            _ => return Ok(member),
        };
        let substitution =
            Substitution::new(parameters.iter().map(|parameter| parameter.id), arguments);
        self.types
            .substitute(member, &substitution)
            .map_err(|parameter| {
                vec![incomplete_substitution(
                    parameter,
                    self.structs
                        .first()
                        .map_or(Span::in_source(SourceId(0), 0, 0), |info| info.span),
                )]
            })
    }

    fn block(&mut self, b: &AstBlock, nested: bool) -> Result<HirBlock, Vec<Diagnostic>> {
        if nested {
            self.scopes.push(BTreeMap::new())
        }
        let mut statements = vec![];
        let mut ended = false;
        for s in &b.statements {
            if ended {
                return Err(vec![Diagnostic::new(
                    "E0208",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "unreachable statement",
                    Some(s.span),
                )]);
            }
            if let AstStmtKind::Assign { place, .. } = &s.kind
                && matches!(&place.kind,AstExprKind::Name(n) if n == "this")
                && self.class_method.is_some()
            {
                return Err(vec![classes::error(
                    "E0404",
                    "this cannot be rebound",
                    s.span,
                )]);
            }
            if let AstStmtKind::Assign { place, value } = &s.kind
                && let (AstExprKind::Name(destination), AstExprKind::Name(source)) =
                    (&place.kind, &value.kind)
                && destination == source
                && let Some(local) = self.lookup(destination)
                && !self.types.guarantees_copy(self.locals[local.0 as usize].ty)
            {
                statements.push(HirStmt {
                    kind: HirStmtKind::Nop,
                    span: s.span,
                    compiler_generated: false,
                });
                continue;
            }
            let kind = match &s.kind {
                AstStmtKind::Local {
                    mutability,
                    const_span: _,
                    ty,
                    name,
                    initializer,
                } => {
                    if self.import_bindings[self.module.0 as usize].contains(name) {
                        return Err(vec![Diagnostic::new(
                            "E0235",
                            Phase::Semantic,
                            DiagnosticCategory::Name,
                            format!("local `{name}` conflicts with a namespace import binding"),
                            Some(s.span),
                        )]);
                    }
                    if name == "this" && self.class_method.is_some() {
                        return Err(vec![classes::error(
                            "E0404",
                            "this cannot be rebound or shadowed",
                            s.span,
                        )]);
                    }
                    if name == "base" && self.class_method.is_some() {
                        return Err(vec![classes::error(
                            "E0422",
                            "base is a contextual call designator and cannot be stored",
                            s.span,
                        )]);
                    }
                    if self.scopes.last().is_some_and(|x| x.contains_key(name)) {
                        return Err(vec![duplicate("local", name, s.span)]);
                    }
                    let expectation = self.resolve_local_type_expectation(ty)?;
                    let (ty, initializer) = match expectation {
                        LocalTypeExpectation::Exact(ty) => {
                            let initializer = self.expression(initializer, Some(ty))?.expr;
                            (ty, initializer)
                        }
                        LocalTypeExpectation::InferRoot(pattern) => {
                            let initializer = self.expression(initializer, None).map_err(
                                |mut diagnostics| {
                                    if let Some(diagnostic) = diagnostics.first_mut()
                                        && matches!(diagnostic.code, "E0263" | "E0451")
                                    {
                                        diagnostic.code = "E0462";
                                        diagnostic.message = format!(
                                            "initializer does not determine all arguments of `{}`: {}",
                                            pattern.source_name, diagnostic.message
                                        );
                                    }
                                    diagnostics
                                },
                            )?.expr;
                            let ty = self.adopt_local_pattern(
                                &pattern,
                                initializer.ty,
                                initializer.span,
                            )?;
                            (ty, initializer)
                        }
                    };
                    if ty == TypeId::VOID {
                        return Err(vec![type_error(
                            "void is not a source-storable local type",
                            s.span,
                        )]);
                    }
                    let local = LocalId(self.locals.len() as u32);
                    self.locals.push(HirLocal {
                        id: local,
                        name: name.clone(),
                        ty,
                        span: s.span,
                        parameter: false,
                        source_binding: true,
                        mutability: *mutability,
                        address_taken: false,
                    });
                    self.scopes.last_mut().unwrap().insert(name.clone(), local);
                    if self.types.nullable_payload(ty).is_some() {
                        let state = match initializer.kind {
                            HirExprKind::NullableNull { .. } => NullState::Null,
                            HirExprKind::NullableInject { .. } => NullState::NonNull,
                            _ => NullState::Unknown,
                        };
                        self.null_states.insert(local, state);
                    }
                    HirStmtKind::Local { local, initializer }
                }
                AstStmtKind::Assign { place, value } => {
                    if let Some(initializer) = self.class_field_write(place, value) {
                        let initializer = initializer?;
                        let kind = self.class_sink(initializer, s.span);
                        statements.push(HirStmt {
                            kind,
                            span: s.span,
                            compiler_generated: false,
                        });
                        continue;
                    }
                    let place = self.resolve_expr_place(place, true)?;
                    if let Some(local) = self.const_inline_root(&place) {
                        let name = &self.locals[local.0 as usize].name;
                        let message = if place.projections.is_empty() {
                            format!("cannot assign to const binding '{name}'")
                        } else {
                            format!("cannot mutate storage of const binding '{name}'")
                        };
                        return Err(vec![Diagnostic::new(
                            "E0372",
                            Phase::Semantic,
                            DiagnosticCategory::Type,
                            message,
                            Some(s.span),
                        )]);
                    }
                    if place.ty == TypeId::STRING
                        && let HirPlaceBase::Local(local) = place.base
                        && !place.projections.is_empty()
                    {
                        self.locals[local.0 as usize].address_taken = true;
                    }
                    if !self.types.guarantees_copy(place.ty)
                        && place.ty != TypeId::STRING
                        && (!place.projections.is_empty()
                            || matches!(place.base, HirPlaceBase::Dereference { .. }))
                    {
                        return Err(vec![Diagnostic::new(
                            "E0297",
                            Phase::Semantic,
                            DiagnosticCategory::Type,
                            "partial replacement of a non-Copy aggregate is unsupported",
                            Some(s.span),
                        )]);
                    }
                    if let HirPlaceBase::Local(local) = &place.base
                        && place.projections.is_empty()
                        && (self
                            .types
                            .reference_info(self.locals[local.0 as usize].ty)
                            .is_some()
                            || self
                                .types
                                .borrowed_view_info(self.locals[local.0 as usize].ty)
                                .is_some())
                    {
                        return Err(vec![Diagnostic::new(
                            "E0277",
                            Phase::Semantic,
                            DiagnosticCategory::Type,
                            "borrowed reference/view locals are single-initialization bindings and cannot be rebound",
                            Some(s.span),
                        )]);
                    }
                    let value = self
                        .expression(value, Some(place.ty))
                        .map_err(|mut ds| {
                            if !place.projections.is_empty() {
                                if let Some(diagnostic) = ds.first_mut() {
                                    diagnostic.code = "E0245";
                                    diagnostic.message = format!(
                                        "field assignment requires {}: {}",
                                        self.type_name(place.ty),
                                        diagnostic.message
                                    );
                                }
                            }
                            ds
                        })?
                        .expr;
                    if let HirPlaceBase::Local(local) = &place.base
                        && place.projections.is_empty()
                        && self.types.nullable_payload(place.ty).is_some()
                    {
                        let state = match value.kind {
                            HirExprKind::NullableNull { .. } => NullState::Null,
                            HirExprKind::NullableInject { .. } => NullState::NonNull,
                            _ => NullState::Unknown,
                        };
                        self.null_states.insert(*local, state);
                    }
                    HirStmtKind::Assign { place, value }
                }
                AstStmtKind::Expr(expression) => self.effect_statement(expression)?,
                AstStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => {
                    let condition_ast = condition;
                    let before_null = self.null_states.clone();
                    let condition = self.expression(condition_ast, Some(TypeId::BOOL))?.expr;
                    self.null_states.clone_from(&before_null);
                    self.refine_for_condition(condition_ast, true);
                    let before = self.initialized_fields.clone();
                    let then_block = self.block(then_block, true)?;
                    let then_fields = self.initialized_fields.clone();
                    let then_null = self.null_states.clone();
                    self.initialized_fields.clone_from(&before);
                    self.null_states.clone_from(&before_null);
                    self.refine_for_condition(condition_ast, false);
                    let else_block = else_block
                        .as_ref()
                        .map(|b| self.block(b, true))
                        .transpose()?;
                    let else_fields = self.initialized_fields.clone();
                    let else_null = self.null_states.clone();
                    self.null_states = Self::joined_null_states(&then_null, &else_null);
                    self.initialized_fields =
                        then_fields.intersection(&else_fields).copied().collect();
                    // An owning field cannot have a path-dependent replacement state.
                    for field in then_fields.symmetric_difference(&else_fields) {
                        if self
                            .types
                            .class_field(*field)
                            .is_some_and(|f| self.types.needs_drop(f.ty))
                        {
                            return Err(vec![classes::error(
                                "E0403",
                                "owning field initialization must agree at a branch join",
                                s.span,
                            )]);
                        }
                    }
                    HirStmtKind::If {
                        condition,
                        then_block,
                        else_block,
                    }
                }
                AstStmtKind::While { condition, body } => {
                    let condition_ast = condition;
                    let mut written_roots = BTreeSet::new();
                    let mut has_call = false;
                    nullable_loop_block_effects(body, &mut written_roots, &mut has_call);
                    for name in written_roots {
                        if let Some(local) = self.lookup(&name)
                            && self
                                .types
                                .nullable_payload(self.locals[local.0 as usize].ty)
                                .is_some()
                        {
                            self.null_states.insert(local, NullState::Unknown);
                        }
                    }
                    if has_call {
                        self.invalidate_nullable_aliases_after_mutating_call();
                    }
                    let before_null = self.null_states.clone();
                    let condition = self.expression(condition_ast, Some(TypeId::BOOL))?.expr;
                    self.null_states.clone_from(&before_null);
                    self.refine_for_condition(condition_ast, true);
                    let before = self.initialized_fields.clone();
                    self.loop_depth += 1;
                    let body = self.block(body, true)?;
                    self.loop_depth -= 1;
                    self.null_states.clone_from(&before_null);
                    self.refine_for_condition(condition_ast, false);
                    if before != self.initialized_fields {
                        return Err(vec![classes::error(
                            "E0403",
                            "field initialization inside a potentially repeated loop is unavailable",
                            s.span,
                        )]);
                    }
                    HirStmtKind::While { condition, body }
                }
                AstStmtKind::ForIn {
                    binding,
                    iterable,
                    body,
                } => {
                    let loop_id = LoopId(self.next_loop);
                    self.next_loop += 1;
                    if let AstExprKind::Range { start, step, end } = &iterable.kind {
                        if let Some(binding_ty) = &binding.ty {
                            let resolved = self.resolve_source_type(binding_ty)?;
                            if resolved != TypeId::INT64 {
                                return Err(vec![Diagnostic::new(
                                    "E0441",
                                    Phase::Semantic,
                                    DiagnosticCategory::Type,
                                    "ITERATION-V1 range bindings must be exactly int/int64",
                                    Some(binding_ty.span),
                                )]);
                            }
                        }
                        // Each call to expression is made once and in source order.
                        let start = self.expression(start, Some(TypeId::INT64))?.expr;
                        let (step, step_is_implicit) = if let Some(step) = step {
                            let checked = self.expression(step, Some(TypeId::INT64))?;
                            if matches!(checked.constant, Some(ConstantValue::Integer(0))) {
                                return Err(vec![Diagnostic::new(
                                    "E0442",
                                    Phase::Semantic,
                                    DiagnosticCategory::Type,
                                    "range step must not be zero",
                                    Some(step.span),
                                )]);
                            }
                            (checked.expr, false)
                        } else {
                            (
                                HirExpr {
                                    kind: HirExprKind::Int(1),
                                    ty: TypeId::INT64,
                                    span: iterable.span,
                                },
                                true,
                            )
                        };
                        let end = self.expression(end, Some(TypeId::INT64))?.expr;
                        let local = LocalId(self.locals.len() as u32);
                        self.locals.push(HirLocal {
                            id: local,
                            name: binding.name.clone(),
                            ty: TypeId::INT64,
                            span: binding.span,
                            parameter: false,
                            source_binding: false,
                            mutability: crate::BindingMutability::Mutable,
                            address_taken: false,
                        });
                        self.scopes.push(BTreeMap::new());
                        self.scopes
                            .last_mut()
                            .unwrap()
                            .insert(binding.name.clone(), local);
                        self.loop_depth += 1;
                        let body = self.block(body, false)?;
                        self.loop_depth -= 1;
                        self.scopes.pop();
                        HirStmtKind::ForRange {
                            loop_id,
                            binding: local,
                            item_type: TypeId::INT64,
                            start,
                            step,
                            end,
                            step_is_implicit,
                            body,
                        }
                    } else {
                        let is_place = matches!(
                            iterable.kind,
                            AstExprKind::Name(_)
                                | AstExprKind::Field { .. }
                                | AstExprKind::Index { .. }
                                | AstExprKind::Unary {
                                    op: AstUnaryOp::Dereference,
                                    ..
                                }
                        );
                        let (iterable_type, source) = if is_place {
                            let place = self.resolve_expr_place(iterable, false)?;
                            (place.ty, CollectionIterationSource::Borrowed(place))
                        } else {
                            let initializer = self.expression(iterable, None)?.expr;
                            let iterable_type = initializer.ty;
                            let root = LocalId(self.locals.len() as u32);
                            self.locals.push(HirLocal {
                                id: root,
                                name: format!("$for_iterable_{}", loop_id.0),
                                ty: iterable_type,
                                span: iterable.span,
                                parameter: false,
                                source_binding: false,
                                mutability: crate::BindingMutability::Mutable,
                                address_taken: true,
                            });
                            (
                                iterable_type,
                                CollectionIterationSource::Temporary { root, initializer },
                            )
                        };
                        let (item_type, structural_borrow) =
                            if let Some(item) = self.types.array_element(iterable_type) {
                                (item, false)
                            } else if let Some(item) = self.types.list_element(iterable_type) {
                                (item, true)
                            } else {
                                return Err(vec![Diagnostic::new(
                                    "E0441",
                                    Phase::Semantic,
                                    DiagnosticCategory::Unsupported,
                                    "for-in admits only Range<int>, Array<T>, or List<T>",
                                    Some(iterable.span),
                                )]);
                            };
                        let (binding_type, category) = if self.types.guarantees_copy(item_type) {
                            (item_type, IterationBindingCategory::CopyValue)
                        } else {
                            (
                                self.types.intern_reference(item_type, false),
                                IterationBindingCategory::SharedElementBorrow,
                            )
                        };
                        if let Some(binding_ty) = &binding.ty {
                            let resolved = self.resolve_source_type(binding_ty)?;
                            if resolved != binding_type {
                                return Err(vec![Diagnostic::new(
                                    "E0444",
                                    Phase::Semantic,
                                    DiagnosticCategory::Type,
                                    format!(
                                        "for-in binding must be exactly {}; per-element conversion is not permitted",
                                        self.type_name(binding_type)
                                    ),
                                    Some(binding_ty.span),
                                )]);
                            }
                        }
                        let local = LocalId(self.locals.len() as u32);
                        self.locals.push(HirLocal {
                            id: local,
                            name: binding.name.clone(),
                            ty: binding_type,
                            span: binding.span,
                            parameter: false,
                            source_binding: false,
                            mutability: crate::BindingMutability::Mutable,
                            address_taken: false,
                        });
                        self.scopes.push(BTreeMap::new());
                        self.scopes
                            .last_mut()
                            .unwrap()
                            .insert(binding.name.clone(), local);
                        self.loop_depth += 1;
                        let body = self.block(body, false)?;
                        self.loop_depth -= 1;
                        self.scopes.pop();
                        HirStmtKind::ForCollection {
                            loop_id,
                            binding: local,
                            iterable_type,
                            item_type,
                            binding_type,
                            category,
                            source,
                            structural_borrow,
                            body,
                        }
                    }
                }
                AstStmtKind::Match {
                    mode,
                    scrutinee,
                    arms,
                } => self.match_statement(*mode, scrutinee, arms)?,
                AstStmtKind::Throw(value) => {
                    if self.inside_finally != 0 {
                        return Err(vec![classes::error(
                            "E0438",
                            "finally must be non-throwing; throw and bare throw are unavailable",
                            s.span,
                        )]);
                    }
                    if let Some(value) = value {
                        let value = self.expression(value, None)?.expr;
                        let Some(class) = self.types.class_id(value.ty) else {
                            return Err(vec![classes::error(
                                "E0432",
                                "throw requires an owning class value derived from Exception",
                                s.span,
                            )]);
                        };
                        if !self.types.is_exception_class(class) {
                            return Err(vec![classes::error(
                                "E0432",
                                "only nominal subclasses of Exception can be thrown",
                                s.span,
                            )]);
                        }
                        let transfer = matches!(
                            value.kind,
                            HirExprKind::Class(ref op)
                                if matches!(op.as_ref(), ClassOp::Construct { .. } | ClassOp::HandleTransfer { .. } | ClassOp::ClassUpcast { transfer: true, .. })
                        );
                        HirStmtKind::Throw {
                            value,
                            class,
                            transfer,
                            drops: Vec::new(),
                        }
                    } else {
                        let Some(catch) = self.active_catches.last().copied() else {
                            return Err(vec![classes::error(
                                "E0434",
                                "bare `throw;` is legal only inside a lexical catch",
                                s.span,
                            )]);
                        };
                        HirStmtKind::Rethrow {
                            catch,
                            drops: Vec::new(),
                        }
                    }
                }
                AstStmtKind::Try {
                    body,
                    catches,
                    finally,
                } => {
                    if self
                        .class_method
                        .as_ref()
                        .is_some_and(|(_, method)| method.initializing)
                    {
                        return Err(vec![classes::error(
                            "E0436",
                            "try/catch/finally is unavailable inside init until local handler rollback is implemented",
                            s.span,
                        )]);
                    }
                    let body = self.block(body, true)?;
                    let mut previous = Vec::new();
                    let mut handlers = Vec::new();
                    for catch in catches {
                        let ty = self.resolve_source_type(&catch.ty)?;
                        let Some(class) = self.types.class_id(ty) else {
                            return Err(vec![classes::error(
                                "E0433",
                                "catch type must be Exception or a nominal subclass",
                                catch.ty.span,
                            )]);
                        };
                        if !self.types.is_exception_class(class) {
                            return Err(vec![classes::error(
                                "E0433",
                                "catch type must be Exception or a nominal subclass",
                                catch.ty.span,
                            )]);
                        }
                        if previous
                            .iter()
                            .any(|earlier| self.types.is_subclass(class, *earlier))
                        {
                            return Err(vec![classes::error(
                                "E0435",
                                "catch is unreachable because an earlier handler covers it",
                                catch.span,
                            )]);
                        }
                        previous.push(class);
                        let id = CatchId(self.next_catch);
                        self.next_catch += 1;
                        self.scopes.push(BTreeMap::new());
                        if self.scopes.last().unwrap().contains_key(&catch.name) {
                            unreachable!();
                        }
                        let binding = LocalId(self.locals.len() as u32);
                        self.locals.push(HirLocal {
                            id: binding,
                            name: catch.name.clone(),
                            ty,
                            span: catch.span,
                            parameter: false,
                            source_binding: false,
                            mutability: crate::BindingMutability::Mutable,
                            address_taken: false,
                        });
                        self.scopes
                            .last_mut()
                            .unwrap()
                            .insert(catch.name.clone(), binding);
                        self.active_catches.push(id);
                        let handler = self.block(&catch.body, false)?;
                        self.active_catches.pop();
                        self.scopes.pop();
                        handlers.push(HirCatch {
                            id,
                            class,
                            binding,
                            body: handler,
                            span: catch.span,
                        });
                    }
                    let finally = if let Some(finally) = finally {
                        if !matches!(
                            self.types.get(self.return_type),
                            Some(TypeData::Bool | TypeData::Integer(_) | TypeData::Float(_))
                        ) {
                            return Err(vec![classes::error(
                                "E0438",
                                "EXCEPTION-V4 finally currently preserves scalar return payloads only",
                                finally.span,
                            )]);
                        }
                        if ast_block_has_call(finally) {
                            return Err(vec![classes::error(
                                "E0438",
                                "finally must be non-throwing in EXCEPTION-V4; calls and construction are unavailable",
                                finally.span,
                            )]);
                        }
                        let id = FinallyId(self.next_finally);
                        self.next_finally += 1;
                        self.inside_finally += 1;
                        let body = self.block(finally, true)?;
                        self.inside_finally -= 1;
                        Some(HirFinally {
                            id,
                            body,
                            span: finally.span,
                        })
                    } else {
                        None
                    };
                    HirStmtKind::Try {
                        body,
                        catches: handlers,
                        finally,
                    }
                }
                AstStmtKind::Return(v) => {
                    if self.inside_finally != 0 {
                        return Err(vec![classes::error(
                            "E0438",
                            "return is unavailable inside finally",
                            s.span,
                        )]);
                    }
                    if let Some((class, method)) = &self.class_method
                        && method.initializing
                        && self.types.classes[class.0 as usize]
                            .fields
                            .iter()
                            .any(|f| !self.initialized_fields.contains(&f.id))
                    {
                        return Err(vec![classes::error(
                            "E0403",
                            "init completes with uninitialized fields",
                            s.span,
                        )]);
                    }
                    let value = match (v, self.return_type) {
                        (None, TypeId::VOID) => HirExpr {
                            kind: HirExprKind::Unit,
                            ty: TypeId::VOID,
                            span: s.span,
                        },
                        (None, _) => {
                            return Err(vec![type_error(
                                "a value is required when returning from a non-void function",
                                s.span,
                            )]);
                        }
                        (Some(_), TypeId::VOID) => {
                            return Err(vec![type_error(
                                "a void function cannot return a value",
                                s.span,
                            )]);
                        }
                        (Some(value), _) => self.expression(value, Some(self.return_type))?.expr,
                    };
                    HirStmtKind::Return {
                        value,
                        drops: Vec::new(),
                    }
                }
                AstStmtKind::Break => {
                    if self.inside_finally != 0 {
                        return Err(vec![classes::error(
                            "E0438",
                            "break is unavailable inside finally",
                            s.span,
                        )]);
                    }
                    if self.loop_depth == 0 {
                        return Err(vec![classes::error(
                            "E0209",
                            "break is legal only inside a loop",
                            s.span,
                        )]);
                    }
                    HirStmtKind::Break { drops: Vec::new() }
                }
                AstStmtKind::Continue => {
                    if self.inside_finally != 0 {
                        return Err(vec![classes::error(
                            "E0438",
                            "continue is unavailable inside finally",
                            s.span,
                        )]);
                    }
                    if self.loop_depth == 0 {
                        return Err(vec![classes::error(
                            "E0209",
                            "continue is legal only inside a loop",
                            s.span,
                        )]);
                    }
                    HirStmtKind::Continue { drops: Vec::new() }
                }
            };
            let hs = HirStmt {
                kind,
                span: s.span,
                compiler_generated: false,
            };
            ended = statement_abrupt(&hs);
            statements.push(hs)
        }
        if nested {
            self.scopes.pop();
        }
        Ok(HirBlock {
            statements,
            exit_drops: Vec::new(),
            span: b.span,
        })
    }

    fn effect_statement(&mut self, expression: &AstExpr) -> Result<HirStmtKind, Vec<Diagnostic>> {
        if let AstExprKind::Call {
            callee,
            type_arguments,
            args,
        } = &expression.kind
            && !self.names[self.module.0 as usize].contains_key(callee)
            && self.lookup(callee).is_none()
            && matches!(
                crate::prelude_symbol(callee),
                Some(crate::CoreSymbol::Print | crate::CoreSymbol::Println)
            )
        {
            if !type_arguments.is_empty() || args.len() != 1 {
                return Err(vec![type_error(
                    "print/println accept exactly one string and no type arguments",
                    expression.span,
                )]);
            }
            let value = self.string_borrow_operand(&args[0])?;
            return Ok(HirStmtKind::StringOutput {
                function: crate::CoreFunction::resolve(
                    crate::prelude_symbol(callee).expect("checked Core output symbol"),
                    TypeId::STRING,
                ),
                value,
                newline: callee == "println",
            });
        }
        if !matches!(&expression.kind, AstExprKind::Call { callee, .. }
            if matches!(callee.as_str(), "push" | "reserve"))
        {
            let initializer = self.expression(expression, None)?.expr;
            if !matches!(
                initializer.kind,
                HirExprKind::Call { .. } | HirExprKind::IndirectCall { .. } | HirExprKind::Class(_)
            ) || (initializer.ty != TypeId::VOID && !self.types.guarantees_copy(initializer.ty))
            {
                return Err(vec![Diagnostic::new(
                    "E0311",
                    Phase::Semantic,
                    DiagnosticCategory::Unsupported,
                    "a discarded declaration call must return Copy; bind owning results explicitly",
                    Some(expression.span),
                )]);
            }
            // A Copy sink uses existing call evaluation/ownership machinery and
            // has no cleanup obligation or source-visible binding.
            let local = LocalId(self.locals.len() as u32);
            self.locals.push(HirLocal {
                id: local,
                name: format!("$discard{}", local.0),
                ty: initializer.ty,
                span: expression.span,
                parameter: false,
                source_binding: false,
                mutability: crate::BindingMutability::Mutable,
                address_taken: false,
            });
            return Ok(HirStmtKind::Local { local, initializer });
        }
        let AstExprKind::Call {
            callee,
            type_arguments,
            args,
        } = &expression.kind
        else {
            return Err(vec![Diagnostic::new(
                "E0311",
                Phase::Semantic,
                DiagnosticCategory::Unsupported,
                "effect statements require push/reserve or a declared call with a Copy result",
                Some(expression.span),
            )]);
        };
        if !type_arguments.is_empty() || args.len() != 2 {
            return Err(vec![Diagnostic::new(
                "E0311",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "push/reserve expect exactly a writable List<T> place and one value, with no type arguments",
                Some(expression.span),
            )]);
        }
        let target = self.resolve_expr_place(&args[0], true)?;
        let Some(element) = self.types.list_element(target.ty) else {
            return Err(vec![Diagnostic::new(
                "E0311",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("{callee} target must be a writable List<T> place"),
                Some(args[0].span),
            )]);
        };
        if callee == "push" {
            let value = self.expression(&args[1], Some(element))?.expr;
            Ok(HirStmtKind::ListPush {
                target,
                value,
                mutation: StructuralMutation::Push,
            })
        } else {
            let requested_capacity = self.expression(&args[1], Some(TypeId::USIZE))?.expr;
            Ok(HirStmtKind::ListReserve {
                target,
                requested_capacity,
                mutation: StructuralMutation::Reserve,
            })
        }
    }

    fn match_statement(
        &mut self,
        source_mode: AstMatchMode,
        scrutinee: &AstExpr,
        arms: &[AstMatchArm],
    ) -> Result<HirStmtKind, Vec<Diagnostic>> {
        let mode = match source_mode {
            AstMatchMode::Value => MatchMode::Value,
            AstMatchMode::SharedRef => MatchMode::SharedRef,
            AstMatchMode::MutableRef => MatchMode::MutableRef,
        };
        let scrutinee = if mode == MatchMode::Value {
            self.expression(scrutinee, None)?.expr
        } else {
            let mutable = mode == MatchMode::MutableRef;
            let place =
                self.resolve_expr_place(scrutinee, mutable)
                    .map_err(|mut diagnostics| {
                        if let Some(diagnostic) = diagnostics.first_mut() {
                            diagnostic.code = if mutable { "E0302" } else { "E0301" };
                            diagnostic.message = if mutable {
                                "`match (ref mut ...)` requires a writable addressable enum place"
                                    .into()
                            } else {
                                "`match (ref ...)` requires an addressable enum place".into()
                            };
                        }
                        diagnostics
                    })?;
            if let HirPlaceBase::Local(local) = &place.base
                && !place
                    .projections
                    .iter()
                    .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
            {
                self.locals[local.0 as usize].address_taken = true;
            }
            let ty = self.types.intern_reference(place.ty, mutable);
            HirExpr {
                kind: HirExprKind::Borrow { place, mutable },
                ty,
                span: scrutinee.span,
            }
        };
        let enum_type = if mode == MatchMode::Value {
            scrutinee.ty
        } else {
            self.types
                .reference_info(scrutinee.ty)
                .expect("match-ref scrutinee was just constructed")
                .0
        };
        let Some(enum_id) = self.types.enum_id(enum_type) else {
            return Err(vec![Diagnostic::new(
                "E0255",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "match scrutinee must be an enum, found {}",
                    self.type_name(enum_type)
                ),
                Some(scrutinee.span),
            )]);
        };
        let enum_info = self.enums[enum_id.0 as usize].clone();
        let mut seen = BTreeSet::new();
        let mut resolved_arms = Vec::new();
        for arm in arms {
            let pattern_ty = AstType {
                kind: crate::AstTypeKind::Named {
                    module: arm.pattern.module.clone(),
                    name: arm.pattern.enum_name.clone(),
                    arguments: arm.pattern.type_arguments.clone(),
                },
                span: arm.pattern.span,
            };
            let resolved_ty = self.resolve_source_type(&pattern_ty)?;
            let Some(pattern_enum) = self.types.enum_id(resolved_ty) else {
                return Err(vec![Diagnostic::new(
                    "E0255",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "match pattern qualifier `{}` is not an enum",
                        arm.pattern.enum_name
                    ),
                    Some(arm.pattern.span),
                )]);
            };
            if pattern_enum != enum_id || resolved_ty != enum_type {
                return Err(vec![Diagnostic::new(
                    "E0257",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "variant pattern belongs to enum `{}`, not `{}`",
                        self.enums[pattern_enum.0 as usize].name, enum_info.name
                    ),
                    Some(arm.pattern.span),
                )]);
            }
            let Some(variant_id) = self.variant_names[enum_id.0 as usize]
                .get(&arm.pattern.variant)
                .copied()
            else {
                return Err(vec![Diagnostic::new(
                    "E0252",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "unknown variant `{}` on enum `{}`",
                        arm.pattern.variant, enum_info.name
                    ),
                    Some(arm.pattern.span),
                )]);
            };
            if !seen.insert(variant_id) {
                return Err(vec![Diagnostic::new(
                    "E0256",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "duplicate match arm for `{}.{}`",
                        enum_info.name, arm.pattern.variant
                    ),
                    Some(arm.pattern.span),
                )]);
            }
            let variant = enum_info.variants[variant_id.index as usize].clone();
            if !arm.pattern.bindings.is_empty()
                && arm.pattern.bindings.len() != variant.payloads.len()
            {
                return Err(vec![Diagnostic::new(
                    "E0253",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "variant `{}.{}` expects {} payload bindings, found {}",
                        enum_info.name,
                        variant.name,
                        variant.payloads.len(),
                        arm.pattern.bindings.len()
                    ),
                    Some(arm.pattern.span),
                )]);
            }
            self.scopes.push(BTreeMap::new());
            let mut bindings = Vec::new();
            for ((name, span), payload) in arm.pattern.bindings.iter().zip(&variant.payloads) {
                if self.scopes.last().unwrap().contains_key(name) {
                    self.scopes.pop();
                    return Err(vec![duplicate("match binding", name, *span)]);
                }
                let payload_ty = self.specialize_member_type(enum_type, payload.ty)?;
                let binding_ty = match mode {
                    MatchMode::Value => payload_ty,
                    MatchMode::SharedRef => self.types.intern_reference(payload_ty, false),
                    MatchMode::MutableRef => self.types.intern_reference(payload_ty, true),
                };
                let local = LocalId(self.locals.len() as u32);
                self.locals.push(HirLocal {
                    id: local,
                    name: name.clone(),
                    ty: binding_ty,
                    span: *span,
                    parameter: false,
                    source_binding: false,
                    mutability: crate::BindingMutability::Mutable,
                    address_taken: false,
                });
                self.scopes.last_mut().unwrap().insert(name.clone(), local);
                bindings.push(HirMatchBinding {
                    local,
                    payload_index: payload.index,
                    ty: binding_ty,
                    span: *span,
                });
            }
            let body = self.block(&arm.body, false)?;
            self.scopes.pop();
            resolved_arms.push(HirMatchArm {
                variant_id,
                bindings,
                body,
                span: arm.span,
            });
        }
        if seen.len() != enum_info.variants.len() {
            let missing = enum_info
                .variants
                .iter()
                .filter(|variant| !seen.contains(&variant.id))
                .map(|variant| variant.name.as_str())
                .collect::<Vec<_>>()
                .join(", ");
            return Err(vec![Diagnostic::new(
                "E0258",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "non-exhaustive match on `{}`; missing: {missing}",
                    enum_info.name
                ),
                Some(scrutinee.span),
            )]);
        }
        Ok(HirStmtKind::Match {
            mode,
            scrutinee,
            enum_type,
            enum_id,
            arms: resolved_arms,
        })
    }

    fn resolve_expr_place(
        &mut self,
        expression: &AstExpr,
        writable: bool,
    ) -> Result<HirPlace, Vec<Diagnostic>> {
        match &expression.kind {
            AstExprKind::Name(name) => {
                if let Some(diagnostic) = self.invalid_default_reference(name, expression.span) {
                    return Err(diagnostic);
                }
                let Some(local) = self.lookup(name) else {
                    return Err(vec![unknown_name(name, expression.span)]);
                };
                Ok(HirPlace {
                    base: HirPlaceBase::Local(local),
                    projections: Vec::new(),
                    ty: self.locals[local.0 as usize].ty,
                })
            }
            AstExprKind::Unary {
                op: AstUnaryOp::Dereference,
                operand,
            } => {
                let reference = self.expression(operand, None)?.expr;
                let Some((pointee, mutable)) = self.types.reference_info(reference.ty) else {
                    return Err(vec![Diagnostic::new(
                        "E0271",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "cannot dereference non-reference type {}",
                            self.type_name(reference.ty)
                        ),
                        Some(expression.span),
                    )]);
                };
                if writable && !mutable {
                    return Err(vec![Diagnostic::new(
                        "E0272",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "cannot mutate through a shared `ref T`; `ref mut T` is required",
                        Some(expression.span),
                    )]);
                }
                Ok(HirPlace {
                    base: HirPlaceBase::Dereference {
                        reference: Box::new(reference),
                        mutable,
                    },
                    projections: Vec::new(),
                    ty: pointee,
                })
            }
            AstExprKind::Field {
                base,
                name,
                name_span,
            } => {
                if let AstExprKind::Name(module) = &base.kind {
                    if self.module_names.contains_key(module) && self.lookup(module).is_none() {
                        return Err(vec![Diagnostic::new(
                            "E0224",
                            Phase::Semantic,
                            DiagnosticCategory::Unsupported,
                            format!("qualified value `{module}.{name}` is not admitted"),
                            Some(expression.span),
                        )]);
                    }
                }
                let mut place = self.resolve_expr_place(base, writable)?;
                self.project_field(&mut place, name, *name_span)?;
                Ok(place)
            }
            AstExprKind::Index { base, indices } => {
                let mut place = self.resolve_expr_place(base, writable)?;
                let rank = if self.types.matrix_like_element(place.ty).is_some() {
                    2
                } else {
                    1
                };
                if indices.len() != rank {
                    return Err(vec![Diagnostic::new(
                        "E0334",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "{} indexing expects {rank} indices, found {}",
                            self.type_name(place.ty),
                            indices.len()
                        ),
                        Some(expression.span),
                    )]);
                }
                let (element_type, mutable) = if let Some(element) =
                    self.types.buffer_element(place.ty)
                {
                    (element, true)
                } else if let Some(element) = self.types.matrix_element(place.ty) {
                    (element, true)
                } else if let Some(element) = self.types.vector_element(place.ty) {
                    (element, true)
                } else if let Some(element) = self.types.array_element(place.ty) {
                    (element, true)
                } else if let Some(element) = self.types.list_element(place.ty) {
                    (element, true)
                } else if let Some((element, mutable)) = self.types.borrowed_view_info(place.ty) {
                    (element, mutable)
                } else {
                    return Err(vec![Diagnostic::new(
                        "E0287",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "checked indexing requires Buffer/Array/List/Vector/View, found {}",
                            self.type_name(place.ty)
                        ),
                        Some(expression.span),
                    )]);
                };
                if writable && !mutable {
                    return Err(vec![Diagnostic::new(
                        "E0288",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "cannot mutate through read-only View<T>; ViewMut<T> is required",
                        Some(expression.span),
                    )]);
                }
                let index = self.expression(&indices[0], Some(TypeId::USIZE))?.expr;
                let column = indices
                    .get(1)
                    .map(|c| {
                        self.expression(c, Some(TypeId::USIZE))
                            .map(|c| Box::new(c.expr))
                    })
                    .transpose()?;
                place.projections.push(HirPlaceProjection::Index {
                    index: Box::new(index),
                    column,
                    element_type,
                    checked: true,
                    semantics: self
                        .types
                        .index_semantics(place.ty)
                        .expect("indexable type"),
                });
                place.ty = element_type;
                Ok(place)
            }
            _ => Err(vec![Diagnostic::new(
                "E0270",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "borrow/assignment target must be an existing addressable Place",
                Some(expression.span),
            )]),
        }
    }

    fn project_field(
        &mut self,
        place: &mut HirPlace,
        name: &str,
        span: Span,
    ) -> Result<(), Vec<Diagnostic>> {
        let Some(struct_id) = self.types.struct_id(place.ty) else {
            return Err(vec![Diagnostic::new(
                "E0244",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!("field access on non-struct type {}", place.ty),
                Some(span),
            )]);
        };
        let Some(field_id) = self.field_names[struct_id.0 as usize].get(name).copied() else {
            return Err(vec![Diagnostic::new(
                "E0243",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!(
                    "unknown field `{name}` on struct `{}`",
                    self.structs[struct_id.0 as usize].name
                ),
                Some(span),
            )]);
        };
        let field = self.structs[struct_id.0 as usize]
            .fields
            .iter()
            .find(|field| field.id == field_id)
            .expect("field-name index is coherent")
            .clone();
        place.projections.push(HirPlaceProjection::Field(field_id));
        place.ty = self.specialize_member_type(place.ty, field.ty)?;
        Ok(())
    }

    fn expression(
        &mut self,
        e: &AstExpr,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if let Some(result) = self.class_expression(e, expected) {
            return result;
        }
        if let AstExprKind::String(value) = &e.kind {
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::String(Box::new(crate::StringOp::Literal {
                            bytes: value.as_bytes().to_vec(),
                        })),
                        ty: TypeId::STRING,
                        span: e.span,
                    },
                    constant: None,
                },
                expected,
            );
        }
        if matches!(e.kind, AstExprKind::Null) {
            let Some(nullable_type) =
                expected.filter(|ty| self.types.nullable_payload(*ty).is_some())
            else {
                let message = expected.map_or_else(
                    || "null requires a concrete nullable expected type".to_string(),
                    |ty| {
                        format!(
                            "cannot use null where non-null {} is required",
                            self.type_name(ty)
                        )
                    },
                );
                return Err(vec![Diagnostic::new(
                    "E0451",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    message,
                    Some(e.span),
                )]);
            };
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::NullableNull { nullable_type },
                    ty: nullable_type,
                    span: e.span,
                },
                constant: None,
            });
        }
        if let AstExprKind::Char(value) = &e.kind {
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Int(i128::from(u32::from(*value))),
                        ty: TypeId::CHAR,
                        span: e.span,
                    },
                    constant: Some(ConstantValue::Integer(i128::from(u32::from(*value)))),
                },
                expected,
            );
        }
        if let AstExprKind::Interpolation(fragments) = &e.kind {
            let mut plan = Vec::with_capacity(fragments.len());
            for fragment in fragments {
                match fragment {
                    crate::AstInterpolationFragment::Text { value, span } => {
                        plan.push(crate::InterpolationFragment::Text {
                            bytes: value.as_bytes().to_vec(),
                            span: *span,
                        });
                    }
                    crate::AstInterpolationFragment::Hole { expression, span } => {
                        let mut value = match self.resolve_expr_place(expression, false) {
                            Ok(place) if place.ty == TypeId::STRING => {
                                let kind = match place.base {
                                    HirPlaceBase::Local(local) if place.projections.is_empty() => {
                                        HirExprKind::Local(local)
                                    }
                                    _ => HirExprKind::Load(place),
                                };
                                HirExpr {
                                    kind,
                                    ty: TypeId::STRING,
                                    span: expression.span,
                                }
                            }
                            _ => self.expression(expression, None)?.expr,
                        };
                        let ty = value.ty;
                        let conversion = if ty == TypeId::STRING {
                            if let HirExprKind::String(op) = value.kind {
                                value = match *op {
                                    crate::StringOp::Alias { source } => source,
                                    other => HirExpr {
                                        kind: HirExprKind::String(Box::new(other)),
                                        ty,
                                        span: value.span,
                                    },
                                };
                            }
                            crate::InterpolationConversion::StringBorrow
                        } else if matches!(
                            self.types.get(ty),
                            Some(
                                TypeData::Bool
                                    | TypeData::Char
                                    | TypeData::Integer(_)
                                    | TypeData::Float(_)
                            )
                        ) {
                            crate::InterpolationConversion::CanonicalScalarFormat
                        } else {
                            return Err(vec![Diagnostic::new(
                                "E0340",
                                Phase::Semantic,
                                DiagnosticCategory::Type,
                                format!(
                                    "type {} is not interpolable in FORMAT-V1",
                                    self.type_name(ty)
                                ),
                                Some(*span),
                            )]);
                        };
                        plan.push(crate::InterpolationFragment::Hole {
                            value,
                            ty,
                            conversion,
                            span: *span,
                        });
                    }
                }
            }
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::String(Box::new(crate::StringOp::Interpolate {
                            fragments: plan,
                            ownership: crate::StringOwnership::Fresh,
                            size_plan: crate::InterpolationSizePlan::CheckedExact,
                        })),
                        ty: TypeId::STRING,
                        span: e.span,
                    },
                    constant: None,
                },
                expected,
            );
        }
        if let AstExprKind::Call {
            callee,
            type_arguments,
            args,
        } = &e.kind
            && (callee == "pop" || callee == "swap_remove" || callee == "remove")
        {
            let indexed = callee != "pop";
            let code = if callee == "remove" {
                "E0322"
            } else if indexed {
                "E0320"
            } else {
                "E0318"
            };
            if !type_arguments.is_empty() || args.len() != if indexed { 2 } else { 1 } {
                return Err(vec![Diagnostic::new(
                    code,
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "{callee} expects a writable List<T> place{} and no type arguments",
                        if indexed { " and a usize index" } else { "" }
                    ),
                    Some(e.span),
                )]);
            }
            let source = self
                .resolve_expr_place(&args[0], true)
                .map_err(|mut errors| {
                    for error in &mut errors {
                        error.code = code;
                    }
                    errors
                })?;
            let Some(element_type) = self.types.list_element(source.ty) else {
                return Err(vec![Diagnostic::new(
                    code,
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!("{callee} requires a writable List<T> place"),
                    Some(e.span),
                )]);
            };
            // The descriptor is an aliasable mutation root. All following reads,
            // moves and cleanup observe the committed initialized-prefix boundary.
            if let HirPlaceBase::Local(local) = source.base {
                self.locals[local.0 as usize].address_taken = true;
            }
            let kind = if indexed {
                let index = self.expression(&args[1], Some(TypeId::USIZE))?.expr;
                if callee == "remove" {
                    HirExprKind::ListRemove {
                        source,
                        index: Box::new(index),
                        element_type,
                        effect: MutationEffect::StableStructuralMutation,
                        invalidation: InvalidationShape::SuffixFrom,
                    }
                } else {
                    HirExprKind::ListSwapRemove {
                        source,
                        index: Box::new(index),
                        element_type,
                        effect: MutationEffect::StableStructuralMutation,
                        invalidation: InvalidationShape::IndexAndTail,
                    }
                }
            } else {
                HirExprKind::ListPop {
                    source,
                    element_type,
                    effect: MutationEffect::StableStructuralMutation,
                }
            };
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind,
                        ty: element_type,
                        span: e.span,
                    },
                    constant: None,
                },
                expected,
            );
        }
        if let AstExprKind::MathematicalLiteral { rows } = &e.kind {
            return self.mathematical_literal(rows, e.span, expected);
        }
        if let AstExprKind::CollectionLiteral(elements) = &e.kind {
            return self.collection_literal(elements, e.span, expected);
        }
        if let AstExprKind::Integer(t) = &e.kind {
            let literal_expected = expected.map(|ty| self.types.nullable_payload(ty).unwrap_or(ty));
            return self
                .integer(t, false, literal_expected, e.span)
                .and_then(|checked| self.coerce(checked, expected));
        }
        if let AstExprKind::Float(t) = &e.kind {
            let literal_expected = expected.map(|ty| self.types.nullable_payload(ty).unwrap_or(ty));
            return self
                .float(t, false, literal_expected, e.span)
                .and_then(|checked| self.coerce(checked, expected));
        }
        if let AstExprKind::Unary {
            op: AstUnaryOp::Negate,
            operand,
        } = &e.kind
        {
            if let AstExprKind::Integer(t) = &operand.kind {
                let literal_expected =
                    expected.map(|ty| self.types.nullable_payload(ty).unwrap_or(ty));
                return self
                    .integer(t, true, literal_expected, e.span)
                    .and_then(|checked| self.coerce(checked, expected));
            }
            if let AstExprKind::Float(t) = &operand.kind {
                let literal_expected =
                    expected.map(|ty| self.types.nullable_payload(ty).unwrap_or(ty));
                return self
                    .float(t, true, literal_expected, e.span)
                    .and_then(|checked| self.coerce(checked, expected));
            }
        }
        let c = match &e.kind {
            AstExprKind::Range { .. } => {
                return Err(vec![Diagnostic::new(
                    "E0441",
                    Phase::Semantic,
                    DiagnosticCategory::Unsupported,
                    "Range values are admitted only as the iterable of for-in in ITERATION-V1",
                    Some(e.span),
                )]);
            }
            AstExprKind::Bool(v) => Checked {
                expr: HirExpr {
                    kind: HirExprKind::Bool(*v),
                    ty: TypeId::BOOL,
                    span: e.span,
                },
                constant: None,
            },
            AstExprKind::Name(n) => {
                if let Some(diagnostic) = self.invalid_default_reference(n, e.span) {
                    return Err(diagnostic);
                }
                if n == "this" && self.class_method.is_some() {
                    return Err(vec![classes::error(
                        "E0404",
                        "borrowed this cannot escape or become an owning source value",
                        e.span,
                    )]);
                }
                let Some(l) = self.lookup(n) else {
                    if let Some(id) = self.names[self.module.0 as usize].get(n).copied() {
                        let signature = self.signatures[id.0 as usize].clone();
                        if !signature.generic_parameters.is_empty() {
                            return Err(vec![Diagnostic::new(
                                "E0355",
                                Phase::Semantic,
                                DiagnosticCategory::Unsupported,
                                "generic function must be explicitly instantiated before use as a value",
                                Some(e.span),
                            )]);
                        }
                        let function_type = self
                            .types
                            .intern_function(
                                signature.parameters.iter().map(|p| p.ty).collect(),
                                signature.return_type,
                            )
                            .expect("collected function signature is valid");
                        if let Some(expected) = expected
                            && expected != function_type
                            && self.types.nullable_payload(expected) != Some(function_type)
                        {
                            return Err(vec![Diagnostic::new(
                                "E0351",
                                Phase::Semantic,
                                DiagnosticCategory::Type,
                                format!(
                                    "function reference has type {}, expected {}",
                                    self.type_name(function_type),
                                    self.type_name(expected)
                                ),
                                Some(e.span),
                            )]);
                        }
                        return self.coerce(
                            Checked {
                                expr: HirExpr {
                                    kind: HirExprKind::FunctionRef {
                                        target: HirCallTarget::Declaration(id),
                                        function_type,
                                    },
                                    ty: function_type,
                                    span: e.span,
                                },
                                constant: None,
                            },
                            expected,
                        );
                    }
                    if crate::prelude_symbol(n).is_some() {
                        return Err(vec![Diagnostic::new(
                            "E0356",
                            Phase::Semantic,
                            DiagnosticCategory::Unsupported,
                            "builtin functions are not values; use a top-level wrapper",
                            Some(e.span),
                        )]);
                    }
                    return Err(vec![unknown_name(n, e.span)]);
                };
                let declared = self.locals[l.0 as usize].ty;
                if let Some(payload) = self.types.nullable_payload(declared)
                    && (expected == Some(payload) || expected.is_none())
                    && self.null_states.get(&l) == Some(&NullState::NonNull)
                {
                    if !self.types.guarantees_copy(payload) {
                        return Err(vec![Diagnostic::new(
                            "E0457",
                            Phase::Semantic,
                            DiagnosticCategory::Type,
                            "cannot move owning payload from refined nullable; move the nullable value or use a future explicit take operation",
                            Some(e.span),
                        )]);
                    }
                    let proof = self.fresh_non_null_proof();
                    return Ok(Checked {
                        expr: HirExpr {
                            kind: HirExprKind::NullablePayload {
                                source: HirPlace {
                                    base: HirPlaceBase::Local(l),
                                    projections: Vec::new(),
                                    ty: declared,
                                },
                                proof,
                                access: NullablePayloadAccess::Copy,
                            },
                            ty: payload,
                            span: e.span,
                        },
                        constant: None,
                    });
                }
                Checked {
                    expr: HirExpr {
                        kind: if self.locals[l.0 as usize].ty == TypeId::STRING {
                            HirExprKind::String(Box::new(crate::StringOp::Alias {
                                source: HirExpr {
                                    kind: HirExprKind::Local(l),
                                    ty: TypeId::STRING,
                                    span: e.span,
                                },
                            }))
                        } else if self.types.guarantees_copy(self.locals[l.0 as usize].ty) {
                            HirExprKind::Local(l)
                        } else if self.types.is_object_owner(self.locals[l.0 as usize].ty) {
                            HirExprKind::Class(Box::new(ClassOp::HandleAlias {
                                source: HirExpr {
                                    kind: HirExprKind::Local(l),
                                    ty: self.locals[l.0 as usize].ty,
                                    span: e.span,
                                },
                            }))
                        } else {
                            HirExprKind::Move(l)
                        },
                        ty: self.locals[l.0 as usize].ty,
                        span: e.span,
                    },
                    constant: None,
                }
            }
            AstExprKind::Call {
                callee,
                type_arguments,
                args,
            } => {
                if callee == "Buffer" {
                    return self.buffer_init(type_arguments, args, e.span, expected);
                }
                if callee == "Array" {
                    return self.array_fill(type_arguments, args, e.span, expected);
                }
                if callee == "transpose" {
                    return self.vector_transpose(type_arguments, args, e.span, expected);
                }
                if callee == "rows" || callee == "columns" {
                    return self.matrix_query(
                        callee == "columns",
                        type_arguments,
                        args,
                        e.span,
                        expected,
                    );
                }
                if matches!(callee.as_str(), "row" | "column" | "row_mut" | "column_mut") {
                    return self.matrix_axis_vector_view(
                        callee,
                        type_arguments,
                        args,
                        e.span,
                        expected,
                    );
                }
                if callee == "dimension" {
                    return self.vector_dimension(type_arguments, args, e.span, expected);
                }
                if callee == "length" {
                    return self.collection_length(type_arguments, args, e.span, expected);
                }
                if callee == "capacity" {
                    return self.list_capacity(type_arguments, args, e.span, expected);
                }
                if matches!(
                    callee.as_str(),
                    "vector_view"
                        | "vector_view_mut"
                        | "matrix_view"
                        | "matrix_view_mut"
                        | "transpose_view"
                        | "transpose_view_mut"
                ) {
                    return self.mathematical_view_init(
                        callee,
                        type_arguments,
                        args,
                        e.span,
                        expected,
                    );
                }
                if callee == "view" || callee == "view_mut" {
                    return self.view_init(
                        callee == "view_mut",
                        type_arguments,
                        args,
                        e.span,
                        expected,
                    );
                }
                if matches!(callee.as_str(), "VectorView" | "VectorViewMut") {
                    return Err(vec![Diagnostic::new(
                        "E0338",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "VectorView has no descriptor constructor; use vector_view or transpose_view with an existing place",
                        Some(e.span),
                    )]);
                }
                let resolved_arguments = self.resolve_type_arguments(type_arguments)?;
                if let Some(target) = builtin(callee)
                    .or_else(|| self.aliases[self.module.0 as usize].get(callee).copied())
                {
                    if self.types.struct_id(target).is_some() {
                        let target = self.apply_named_type(target, &resolved_arguments, e.span)?;
                        self.struct_init(target, callee, args, e.span)?
                    } else if self.types.enum_id(target).is_some() {
                        return Err(vec![Diagnostic::new(
                            "E0250",
                            Phase::Semantic,
                            DiagnosticCategory::Syntax,
                            "enum construction requires a qualified variant",
                            Some(e.span),
                        )]);
                    } else {
                        if !resolved_arguments.is_empty() {
                            return Err(vec![generic_call_arity(
                                callee,
                                0,
                                resolved_arguments.len(),
                                e.span,
                            )]);
                        }
                        self.explicit_cast(callee, target, args, e.span)?
                    }
                } else if let Some(id) = self.struct_names[self.module.0 as usize].get(callee) {
                    let target = self.nominal_struct_type(*id, resolved_arguments, e.span)?;
                    self.struct_init(target, callee, args, e.span)?
                } else {
                    self.call(callee, type_arguments, args, e.span, expected)?
                }
            }
            AstExprKind::QualifiedCall {
                module,
                function,
                type_arguments,
                args,
                parenthesized,
            } => {
                let resolved_arguments = self.resolve_type_arguments(type_arguments)?;
                if let Some(enum_id) = self.local_enum_id(module) {
                    let enum_ty = self.nominal_enum_type(enum_id, resolved_arguments, e.span)?;
                    self.enum_init(enum_ty, function, args, *parenthesized, e.span)?
                } else if !self.imports[self.module.0 as usize].contains_key(module)
                    && let Some((namespace, enum_name)) = module.rsplit_once('.')
                {
                    let enum_ty =
                        self.qualified_enum_type(namespace, enum_name, type_arguments, e.span)?;
                    self.enum_init(enum_ty, function, args, *parenthesized, e.span)?
                } else {
                    self.qualified_apply(module, function, type_arguments, args, e.span)?
                }
            }
            AstExprKind::VariantCall {
                module,
                enum_name,
                type_arguments,
                variant,
                args,
                parenthesized,
            } => {
                let enum_ty =
                    self.qualified_enum_type(module, enum_name, type_arguments, e.span)?;
                self.enum_init(enum_ty, variant, args, *parenthesized, e.span)?
            }
            AstExprKind::Field { base, name, .. } => {
                if let AstExprKind::Name(module) = &base.kind
                    && self.lookup(module).is_none()
                    && let Some(target_module) =
                        self.imports[self.module.0 as usize].get(module).copied()
                    && let Some(id) = self.names[target_module.0 as usize].get(name).copied()
                {
                    self.used_modules.insert(target_module);
                    let signature = self.signatures[id.0 as usize].clone();
                    if !signature.generic_parameters.is_empty() {
                        return Err(vec![Diagnostic::new(
                            "E0355",
                            Phase::Semantic,
                            DiagnosticCategory::Unsupported,
                            "generic function must be explicitly instantiated before use as a value",
                            Some(e.span),
                        )]);
                    }
                    let function_type = self
                        .types
                        .intern_function(
                            signature
                                .parameters
                                .iter()
                                .map(|parameter| parameter.ty)
                                .collect(),
                            signature.return_type,
                        )
                        .expect("collected function signature is valid");
                    if let Some(expected) = expected
                        && expected != function_type
                        && self.types.nullable_payload(expected) != Some(function_type)
                    {
                        return Err(vec![Diagnostic::new(
                            "E0351",
                            Phase::Semantic,
                            DiagnosticCategory::Type,
                            format!(
                                "function reference has type {}, expected {}",
                                self.type_name(function_type),
                                self.type_name(expected)
                            ),
                            Some(e.span),
                        )]);
                    }
                    Checked {
                        expr: HirExpr {
                            kind: HirExprKind::FunctionRef {
                                target: HirCallTarget::Declaration(id),
                                function_type,
                            },
                            ty: function_type,
                            span: e.span,
                        },
                        constant: None,
                    }
                } else if let AstExprKind::Field {
                    base: qualifier,
                    name: enum_name,
                    ..
                } = &base.kind
                    && let AstExprKind::Name(module) = &qualifier.kind
                    && self.lookup(module).is_none()
                    && (self.module_names.contains_key(module)
                        || self.imports[self.module.0 as usize].contains_key(module))
                {
                    let enum_ty = self.qualified_enum_type(module, enum_name, &[], e.span)?;
                    self.enum_init(enum_ty, name, &[], false, e.span)?
                } else if let AstExprKind::Name(type_name) = &base.kind {
                    if let Some(enum_id) = self.local_enum_id(type_name) {
                        let enum_ty = self.nominal_enum_type(enum_id, Vec::new(), e.span)?;
                        self.enum_init(enum_ty, name, &[], false, e.span)?
                    } else {
                        if let Some(local) = self.lookup(type_name) {
                            let receiver_type = self.locals[local.0 as usize].ty;
                            let is_class_method =
                                self.types.object_class(receiver_type).is_some_and(|class| {
                                    self.types.effective_method(class, name).is_some()
                                });
                            let is_interface_method = self
                                .types
                                .interface_identity(receiver_type)
                                .is_some_and(|interface| {
                                    self.types.interfaces()[interface.0 as usize]
                                        .requirements
                                        .iter()
                                        .any(|requirement| requirement.name == *name)
                                });
                            if is_class_method || is_interface_method {
                                return Err(vec![Diagnostic::new(
                                    "E0354",
                                    Phase::Semantic,
                                    DiagnosticCategory::Type,
                                    "bound and method function values are not supported",
                                    Some(e.span),
                                )]);
                            }
                        }
                        let place = self.resolve_expr_place(e, false)?;
                        self.load_place(place, e.span)?
                    }
                } else {
                    let place = self.resolve_expr_place(e, false)?;
                    self.load_place(place, e.span)?
                }
            }
            AstExprKind::Index { .. }
            | AstExprKind::Unary {
                op: AstUnaryOp::Dereference,
                ..
            } => {
                let place = self.resolve_expr_place(e, false)?;
                self.load_place(place, e.span)?
            }
            AstExprKind::QualifiedName { module, member } => {
                return Err(vec![Diagnostic::new(
                    "E0224",
                    Phase::Semantic,
                    DiagnosticCategory::Unsupported,
                    format!("qualified value `{module}.{member}` is not admitted"),
                    Some(e.span),
                )]);
            }
            AstExprKind::Unary {
                op: AstUnaryOp::BorrowShared | AstUnaryOp::BorrowMutable,
                operand,
            } => {
                let mutable = matches!(
                    &e.kind,
                    AstExprKind::Unary {
                        op: AstUnaryOp::BorrowMutable,
                        ..
                    }
                );
                let place = self.resolve_expr_place(operand, mutable)?;
                if mutable && let Some(local) = self.const_inline_root(&place) {
                    return Err(vec![Diagnostic::new(
                        "E0373",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "cannot mutably borrow const storage '{}'",
                            self.locals[local.0 as usize].name
                        ),
                        Some(e.span),
                    )]);
                }
                if let HirPlaceBase::Local(local) = &place.base
                    && !place
                        .projections
                        .iter()
                        .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
                {
                    self.locals[local.0 as usize].address_taken = true;
                    if mutable
                        && self
                            .types
                            .nullable_payload(self.locals[local.0 as usize].ty)
                            .is_some()
                    {
                        self.null_states.insert(*local, NullState::Unknown);
                    }
                }
                if self.types.object_class(place.ty).is_some() {
                    return Err(vec![classes::error(
                        "E0406",
                        "class handle/receiver references are unavailable in OOP-V1",
                        e.span,
                    )]);
                }
                let ty = self.types.intern_reference(place.ty, mutable);
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Borrow { place, mutable },
                        ty,
                        span: e.span,
                    },
                    constant: None,
                }
            }
            AstExprKind::Unary {
                op: AstUnaryOp::Negate,
                operand,
            } => self.negate(operand, e.span)?,
            AstExprKind::Unary {
                op: AstUnaryOp::LogicalNot,
                operand,
            } => {
                let operand = self.expression(operand, Some(TypeId::BOOL))?.expr;
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::LogicalNot {
                            operand: Box::new(operand),
                        },
                        ty: TypeId::BOOL,
                        span: e.span,
                    },
                    constant: None,
                }
            }
            AstExprKind::Binary { op, left, right } => {
                self.binary(*op, left, right, expected, e.span)?
            }
            _ => unreachable!(),
        };
        self.coerce(c, expected)
    }

    fn load_place(&self, place: HirPlace, span: Span) -> Result<Checked, Vec<Diagnostic>> {
        if !self.types.guarantees_copy(place.ty) {
            if let Some(local) = self.const_inline_root(&place) {
                return Err(vec![Diagnostic::new(
                    "E0375",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "cannot partially move from const storage '{}'",
                        self.locals[local.0 as usize].name
                    ),
                    Some(span),
                )]);
            }
            return Err(vec![Diagnostic::new(
                "E0293",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "partial move of non-Copy field `{}` is unsupported",
                    self.type_name(place.ty)
                ),
                Some(span),
            )]);
        }
        Ok(Checked {
            expr: HirExpr {
                ty: place.ty,
                kind: HirExprKind::Load(place),
                span,
            },
            constant: None,
        })
    }

    fn integer(
        &self,
        text: &str,
        neg: bool,
        expected: Option<TypeId>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let ty = expected.unwrap_or(TypeId::INT64);
        // Contextual numeric literals are selected directly in their target
        // type. This is literal typing, not a runtime integer-to-float cast.
        if self.types.float_info(ty).is_some() {
            return self.float(text, neg, Some(ty), span);
        }
        let Some(it) = self.types.integer_info(ty) else {
            return Err(vec![type_error(
                format!("integer literal cannot initialize {}", self.type_name(ty)),
                span,
            )]);
        };
        let mag = text
            .parse::<u128>()
            .map_err(|_| vec![range(self.types, text, ty, span, self.target)])?;
        let value = if neg {
            if mag > 1u128 << 127 {
                return Err(vec![range(self.types, text, ty, span, self.target)]);
            }
            if mag == 1u128 << 127 {
                i128::MIN
            } else {
                -(mag as i128)
            }
        } else {
            i128::try_from(mag).map_err(|_| vec![range(self.types, text, ty, span, self.target)])?
        };
        let (min, max) = it.range(self.target);
        if value < min || value > max {
            return Err(vec![range(
                self.types,
                if neg { "negative integer" } else { text },
                ty,
                span,
                self.target,
            )]);
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Int(value),
                ty,
                span,
            },
            constant: Some(ConstantValue::Integer(value)),
        })
    }
    fn float(
        &self,
        text: &str,
        neg: bool,
        expected: Option<TypeId>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let ty = expected.unwrap_or(TypeId::FLOAT64);
        let Some(ft) = self.types.float_info(ty) else {
            return Err(vec![type_error(
                format!("floating literal cannot initialize {}", self.type_name(ty)),
                span,
            )]);
        };
        let s = if neg { format!("-{text}") } else { text.into() };
        let value = match ft {
            FloatType::Float32 => s
                .parse::<f32>()
                .ok()
                .filter(|v| v.is_finite())
                .map(|v| FloatValue::Float32(v.to_bits())),
            FloatType::Float64 => s
                .parse::<f64>()
                .ok()
                .filter(|v| v.is_finite())
                .map(|v| FloatValue::Float64(v.to_bits())),
        }
        .ok_or_else(|| {
            vec![Diagnostic::new(
                "E0216",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "floating literal `{s}` is outside {} finite range",
                    self.type_name(ty)
                ),
                Some(span),
            )]
        })?;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Float(value),
                ty,
                span,
            },
            constant: Some(ConstantValue::Float(value)),
        })
    }
    fn negate(&mut self, o: &AstExpr, span: Span) -> Result<Checked, Vec<Diagnostic>> {
        let c = self.expression(o, None)?;
        let ty = c.expr.ty;
        let op = match self.types.get(ty) {
            Some(TypeData::Integer(i)) if i.is_signed() => HirUnaryOp::NegateIntegerChecked,
            Some(TypeData::Integer(_)) => {
                return Err(vec![Diagnostic::new(
                    "E0217",
                    Phase::Semantic,
                    DiagnosticCategory::Integer,
                    "unary `-` is invalid for unsigned values",
                    Some(span),
                )]);
            }
            Some(TypeData::Float(_)) => HirUnaryOp::NegateFloat,
            Some(
                TypeData::Interface(_)
                | TypeData::InterfaceKeepalive { .. }
                | TypeData::Class(_)
                | TypeData::ClassToken { .. }
                | TypeData::Void
                | TypeData::Bool
                | TypeData::Char
                | TypeData::String
                | TypeData::Nullable(_)
                | TypeData::Struct(_)
                | TypeData::Enum(_)
                | TypeData::GenericParam(_)
                | TypeData::StructInstance(_, _)
                | TypeData::EnumInstance(_, _)
                | TypeData::Reference { .. }
                | TypeData::Function { .. }
                | TypeData::Buffer { .. }
                | TypeData::Vector { .. }
                | TypeData::Array { .. }
                | TypeData::Matrix { .. }
                | TypeData::List { .. }
                | TypeData::View { .. }
                | TypeData::VectorView { .. }
                | TypeData::MatrixView { .. },
            )
            | None => {
                return Err(vec![type_error(
                    format!("{} cannot be used numerically", self.type_name(ty)),
                    span,
                )]);
            }
        };
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Unary {
                    op,
                    operand: Box::new(c.expr),
                },
                ty,
                span,
            },
            constant: match c.constant {
                Some(ConstantValue::Integer(value)) => {
                    value.checked_neg().map(ConstantValue::Integer)
                }
                Some(ConstantValue::Float(FloatValue::Float32(bits))) => Some(
                    ConstantValue::Float(FloatValue::Float32((-f32::from_bits(bits)).to_bits())),
                ),
                Some(ConstantValue::Float(FloatValue::Float64(bits))) => Some(
                    ConstantValue::Float(FloatValue::Float64((-f64::from_bits(bits)).to_bits())),
                ),
                None => None,
            },
        })
    }
    fn buffer_init(
        &mut self,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if type_arguments.len() != 1 {
            return Err(vec![generic_call_arity(
                "Buffer",
                1,
                type_arguments.len(),
                span,
            )]);
        }
        if args.len() != 2 {
            return Err(vec![Diagnostic::new(
                "E0281",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "Buffer<T> construction expects length and fill value, found {} arguments",
                    args.len()
                ),
                Some(span),
            )]);
        }
        let element = self.resolve_type_arguments(type_arguments)?[0];
        if self.types.contains_generic(element) {
            return Err(vec![Diagnostic::new(
                "E0283",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "Vertical-10 Buffer element type must be concrete",
                Some(span),
            )]);
        }
        if !self.types.is_admitted_buffer_element(element) {
            return Err(vec![Diagnostic::new(
                "E0280",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "Vertical-10 Buffer elements must be concrete Copy/no-drop values without borrowed or owning substructure",
                Some(span),
            )]);
        }
        let ty = self.types.intern_buffer(element);
        if expected.is_some_and(|expected| expected != ty) {
            return Err(vec![type_error(
                format!(
                    "Buffer constructor produces {}, not {}",
                    self.type_name(ty),
                    self.type_name(expected.unwrap())
                ),
                span,
            )]);
        }
        let length = self.expression(&args[0], Some(TypeId::USIZE))?;
        let initial = self.expression(&args[1], Some(element))?.expr;
        if let Some(ConstantValue::Integer(length_value)) = length.constant {
            let layout = layout_of(self.types, element, self.target, self.structs, self.enums)
                .expect("admitted concrete Buffer element has layout");
            if u64::try_from(length_value)
                .ok()
                .and_then(|length| length.checked_mul(layout.size))
                .is_none()
            {
                return Err(vec![Diagnostic::new(
                    "E0282",
                    Phase::Semantic,
                    DiagnosticCategory::Integer,
                    "AllocationSizeOverflow: Buffer length times element size exceeds usize",
                    Some(args[0].span),
                )]);
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::BufferInit {
                    element_type: element,
                    length: Box::new(length.expr),
                    initial: Box::new(initial),
                },
                ty,
                span,
            },
            constant: None,
        })
    }

    fn mathematical_literal(
        &mut self,
        rows: &[Vec<AstExpr>],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let fail = |code, message: String, span| {
            vec![Diagnostic::new(
                code,
                Phase::Semantic,
                DiagnosticCategory::Type,
                message,
                Some(span),
            )]
        };
        let Some(ty) = expected else {
            return Err(fail(
                "E0326",
                "mathematical literal requires a Matrix or Vector expected type".into(),
                span,
            ));
        };
        let matrix = self.types.matrix_element(ty);
        let Some(element_type) = matrix.or_else(|| self.types.vector_element(ty)) else {
            return Err(fail(
                "E0326",
                "mathematical literal requires a Matrix or Vector expected type".into(),
                span,
            ));
        };
        if matrix.is_none() && rows.len() > 1 {
            return Err(fail(
                "E0332",
                "multi-row mathematical literal cannot initialize Vector".into(),
                span,
            ));
        }
        let columns = rows.first().map_or(0, Vec::len);
        for (i, row) in rows.iter().enumerate() {
            if row.len() != columns {
                return Err(fail(
                    "E0333",
                    format!(
                        "ragged Matrix row {}: expected {columns} columns, found {}",
                        i + 1,
                        row.len()
                    ),
                    row.first().map_or(span, |e| e.span),
                ));
            }
        }
        let elements = rows
            .iter()
            .flatten()
            .map(|e| self.expression(e, Some(element_type)).map(|c| c.expr))
            .collect::<Result<Vec<_>, _>>()?;
        let kind = if matrix.is_some() {
            HirExprKind::MatrixInit {
                element_type,
                elements,
                rows: rows.len() as u64,
                columns: columns as u64,
                row_ends: (1..=rows.len()).map(|r| (r * columns) as u64).collect(),
            }
        } else {
            HirExprKind::VectorInit {
                element_type,
                elements,
            }
        };
        Ok(Checked {
            expr: HirExpr { kind, ty, span },
            constant: None,
        })
    }

    fn matrix_query(
        &mut self,
        columns: bool,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let invalid = || {
            vec![Diagnostic::new(
                "E0335",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "rows/columns expects exactly one Matrix/MatrixView/MatrixViewMut place and no type arguments",
                Some(span),
            )]
        };
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(invalid());
        }
        let source = self.resolve_expr_place(&args[0], false)?;
        if self.types.matrix_like_element(source.ty).is_none() {
            return Err(invalid());
        }
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: if columns {
                        HirExprKind::MatrixColumns { source }
                    } else {
                        HirExprKind::MatrixRows { source }
                    },
                    ty: TypeId::USIZE,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn vector_transpose(
        &mut self,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let invalid = |message| {
            vec![Diagnostic::new(
                "E0328",
                Phase::Semantic,
                DiagnosticCategory::Type,
                message,
                Some(span),
            )]
        };
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(invalid(
                "Vector transpose expects exactly one consuming operand and no type arguments",
            ));
        }
        // Derive orientation from the operand, independently of destination context.
        let operand = self.expression(&args[0], None)?.expr;
        if self.types.matrix_element(operand.ty).is_some() {
            return Err(invalid(
                "Matrix transpose is not implemented; transpose accepts only Vector",
            ));
        }
        let Some(TypeData::Vector {
            element,
            orientation,
        }) = self.types.get(operand.ty)
        else {
            return Err(invalid("Vector transpose operand must be an owning Vector"));
        };
        let ty = self.types.intern_vector(*element, orientation.transposed());
        let source_type = operand.ty;
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::VectorTranspose {
                        operand: Box::new(operand),
                        source_type,
                    },
                    ty,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn vector_dimension(
        &mut self,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(vec![Diagnostic::new(
                "E0327",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "dimension expects exactly one Vector/VectorView/VectorViewMut place and no type arguments",
                Some(span),
            )]);
        }
        let source = self.resolve_expr_place(&args[0], false)?;
        if self.types.vector_like_info(source.ty).is_none() {
            return Err(vec![Diagnostic::new(
                "E0327",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "dimension source must be a Vector/VectorView/VectorViewMut place",
                Some(span),
            )]);
        }
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::VectorDimension { source },
                    ty: TypeId::USIZE,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn collection_literal(
        &mut self,
        elements: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let Some(expected_type) = expected else {
            return Err(vec![Diagnostic::new(
                "E0305",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "collection literal requires an expected Array<T> or List<T> type",
                Some(span),
            )]);
        };
        let collection_type = self
            .types
            .nullable_payload(expected_type)
            .unwrap_or(expected_type);
        let (element_type, is_list) =
            if let Some(element) = self.types.array_element(collection_type) {
                (element, false)
            } else if let Some(element) = self.types.list_element(collection_type) {
                (element, true)
            } else {
                return Err(vec![Diagnostic::new(
                    "E0305",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "collection literal cannot initialize {}; expected Array<T> or List<T>",
                        self.type_name(collection_type)
                    ),
                    Some(span),
                )]);
            };
        let mut resolved = Vec::with_capacity(elements.len());
        for element in elements {
            resolved.push(self.expression(element, Some(element_type))?.expr);
        }
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: if is_list {
                        HirExprKind::ListInit {
                            element_type,
                            elements: resolved,
                        }
                    } else {
                        HirExprKind::ArrayInit {
                            element_type,
                            elements: resolved,
                        }
                    },
                    ty: collection_type,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn array_fill(
        &mut self,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if type_arguments.len() != 1 {
            return Err(vec![generic_call_arity(
                "Array",
                1,
                type_arguments.len(),
                span,
            )]);
        }
        if args.len() != 2 {
            return Err(vec![Diagnostic::new(
                "E0306",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "Array<T> fill construction expects length and fill value, found {} arguments",
                    args.len()
                ),
                Some(span),
            )]);
        }
        let element = self.resolve_type_arguments(type_arguments)?[0];
        if !self.types.is_admitted_array_element(element) {
            return Err(vec![Diagnostic::new(
                "E0304",
                Phase::Semantic,
                DiagnosticCategory::Type,
                collection_admission_message(
                    "Array",
                    self.type_name(element),
                    self.types
                        .collection_element_admission(CollectionKind::Array, element),
                ),
                Some(span),
            )]);
        }
        if !self.types.guarantees_copy(element) {
            return Err(vec![Diagnostic::new(
                "E0314",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "Array fill construction duplicates its fill value and therefore requires Copy; {} is non-Copy",
                    self.type_name(element)
                ),
                Some(span),
            )]);
        }
        let ty = self.types.intern_array(element);
        if expected.is_some_and(|expected| expected != ty) {
            return Err(vec![type_error(
                format!(
                    "Array constructor produces {}, not {}",
                    self.type_name(ty),
                    self.type_name(expected.unwrap())
                ),
                span,
            )]);
        }
        let length = self.expression(&args[0], Some(TypeId::USIZE))?;
        let initial = self.expression(&args[1], Some(element))?.expr;
        self.check_allocation_size(&length, element, args[0].span, "Array")?;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::ArrayFill {
                    element_type: element,
                    length: Box::new(length.expr),
                    initial: Box::new(initial),
                },
                ty,
                span,
            },
            constant: None,
        })
    }

    fn collection_length(
        &mut self,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(vec![Diagnostic::new(
                "E0307",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "length expects exactly one Array<T> or List<T> place and no type arguments",
                Some(span),
            )]);
        }
        let source = self.resolve_expr_place(&args[0], false)?;
        let is_list = self.types.list_element(source.ty).is_some();
        if self.types.array_element(source.ty).is_none() && !is_list {
            return Err(vec![Diagnostic::new(
                "E0307",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "length source must be an Array<T> or List<T> place",
                Some(args[0].span),
            )]);
        }
        let checked = Checked {
            expr: HirExpr {
                kind: if is_list {
                    HirExprKind::ListLength { source }
                } else {
                    HirExprKind::ArrayLength { source }
                },
                ty: TypeId::USIZE,
                span,
            },
            constant: None,
        };
        self.coerce(checked, expected)
    }

    fn list_capacity(
        &mut self,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(vec![Diagnostic::new(
                "E0312",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "capacity expects exactly one List<T> place and no type arguments",
                Some(span),
            )]);
        }
        let source = self.resolve_expr_place(&args[0], false)?;
        if self.types.list_element(source.ty).is_none() {
            return Err(vec![Diagnostic::new(
                "E0312",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "capacity source must be a List<T> place",
                Some(args[0].span),
            )]);
        }
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::ListCapacity { source },
                    ty: TypeId::USIZE,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn check_allocation_size(
        &self,
        length: &Checked,
        element: TypeId,
        span: Span,
        collection: &str,
    ) -> Result<(), Vec<Diagnostic>> {
        if let Some(ConstantValue::Integer(length_value)) = length.constant
            && !self.types.contains_generic(element)
        {
            let layout = layout_of(self.types, element, self.target, self.structs, self.enums)
                .expect("admitted concrete contiguous element has layout");
            if u64::try_from(length_value)
                .ok()
                .and_then(|length| length.checked_mul(layout.size))
                .is_none()
            {
                return Err(vec![Diagnostic::new(
                    "E0282",
                    Phase::Semantic,
                    DiagnosticCategory::Integer,
                    format!(
                        "AllocationSizeOverflow: {collection} length times element size exceeds usize"
                    ),
                    Some(span),
                )]);
            }
        }
        Ok(())
    }

    fn matrix_axis_vector_view(
        &mut self,
        name: &str,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let invalid = || {
            vec![Diagnostic::new(
                "E0340",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "row/column projection requires a Matrix/MatrixView/MatrixViewMut Place and one usize index, without type arguments",
                Some(span),
            )]
        };
        if !type_arguments.is_empty() || args.len() != 2 {
            return Err(invalid());
        }
        let mutable = name.ends_with("_mut");
        let source = self.resolve_expr_place(&args[0], mutable)?;
        let element = self
            .types
            .matrix_like_element(source.ty)
            .ok_or_else(invalid)?;
        if mutable
            && self
                .types
                .matrix_view_info(source.ty)
                .is_some_and(|(_, m)| !m)
        {
            return Err(vec![Diagnostic::new(
                "E0341",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "mutable Matrix row/column projection requires writable source capability",
                Some(span),
            )]);
        }
        let fixed_index = Box::new(self.expression(&args[1], Some(TypeId::USIZE))?.expr);
        let axis = if name.starts_with("row") {
            crate::types::Orientation::Row
        } else {
            crate::types::Orientation::Column
        };
        let descriptor = crate::types::MatrixAxisVectorViewDescriptor::derived(axis);
        let ty = self.types.intern_vector_view(element, axis, mutable);
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::MatrixAxisVectorView {
                        source,
                        fixed_index,
                        axis,
                        mutable,
                        descriptor,
                    },
                    ty,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn mathematical_view_init(
        &mut self,
        name: &str,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let invalid = || {
            vec![Diagnostic::new(
                "E0336",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "view creation requires one matching mathematical owner/view place and no type arguments",
                Some(span),
            )]
        };
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(invalid());
        }
        let mutable = name.ends_with("_mut");
        let transpose = name.starts_with("transpose");
        let source = self.resolve_expr_place(&args[0], mutable)?;
        if name.starts_with("vector_view")
            || (transpose && self.types.vector_like_info(source.ty).is_some())
        {
            return self.vector_view_from_place(source, mutable, transpose, span, expected);
        }
        let element = self
            .types
            .matrix_like_element(source.ty)
            .ok_or_else(invalid)?;
        if mutable
            && self
                .types
                .matrix_view_info(source.ty)
                .is_some_and(|(_, m)| !m)
        {
            return Err(vec![Diagnostic::new(
                "E0337",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "mutable matrix view requires writable source capability",
                Some(span),
            )]);
        }
        let descriptor = crate::types::MatrixViewDescriptor::derived(
            self.types.matrix_view_info(source.ty).is_some(),
            transpose,
        );
        let ty = self.types.intern_matrix_view(element, mutable);
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::MatrixView {
                        source,
                        mutable,
                        transpose,
                        descriptor,
                    },
                    ty,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn vector_view_from_place(
        &mut self,
        source: HirPlace,
        mutable: bool,
        transpose: bool,
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let (element, orientation) = self.types.vector_like_info(source.ty).ok_or_else(|| {
            vec![Diagnostic::new(
                "E0338",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "vector_view requires a Vector/VectorView/VectorViewMut place",
                Some(span),
            )]
        })?;
        if mutable
            && self
                .types
                .vector_view_info(source.ty)
                .is_some_and(|(_, _, m)| !m)
        {
            return Err(vec![Diagnostic::new(
                "E0339",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "mutable vector view requires writable source capability",
                Some(span),
            )]);
        }
        let descriptor = crate::types::VectorViewDescriptor::derived(
            self.types.vector_view_info(source.ty).is_some(),
        );
        let orientation = if transpose {
            orientation.transposed()
        } else {
            orientation
        };
        let ty = self.types.intern_vector_view(element, orientation, mutable);
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::VectorView {
                        source,
                        mutable,
                        transpose,
                        descriptor,
                    },
                    ty,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }

    fn view_init(
        &mut self,
        mutable: bool,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if !type_arguments.is_empty() || args.len() != 1 {
            return Err(vec![Diagnostic::new(
                "E0289",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "view/view_mut expects exactly one Buffer place and no explicit type arguments",
                Some(span),
            )]);
        }
        let source = self.resolve_expr_place(&args[0], mutable)?;
        let Some(element) = self.types.owning_contiguous_element(source.ty).filter(|_| {
            self.types.vector_element(source.ty).is_none()
                && self.types.matrix_element(source.ty).is_none()
        }) else {
            return Err(vec![Diagnostic::new(
                "E0289",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "view/view_mut source must be a Buffer<T>, Array<T>, or List<T> place",
                Some(args[0].span),
            )]);
        };
        let ty = self.types.intern_view(element, mutable);
        if expected.is_some_and(|expected| expected != ty) {
            return Err(vec![type_error(
                format!(
                    "view constructor produces {}, not {}",
                    self.type_name(ty),
                    self.type_name(expected.unwrap())
                ),
                span,
            )]);
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::View { source, mutable },
                ty,
                span,
            },
            constant: None,
        })
    }

    fn explicit_cast(
        &mut self,
        spelling: &str,
        target: TypeId,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if args.len() != 1 {
            return Err(vec![Diagnostic::new(
                "E0230",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                format!("conversion target `{spelling}` expects exactly one operand"),
                Some(span),
            )]);
        }
        let operand = match self.expression(&args[0], None) {
            Ok(value) => value,
            Err(diagnostics)
                if self.types.integer_info(target).is_some()
                    && diagnostics.first().is_some_and(|d| d.code == "E0209") =>
            {
                self.expression(&args[0], Some(target))?
            }
            Err(diagnostics) => return Err(diagnostics),
        };
        let source = operand.expr.ty;
        if self.types.reference_info(source).is_some() {
            return Err(vec![Diagnostic::new(
                "E0278",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                "references cannot be cast to numeric values or other reference types",
                Some(span),
            )]);
        }
        if source == TypeId::BOOL || target == TypeId::BOOL {
            return Err(vec![Diagnostic::new(
                "E0232",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                format!(
                    "bool has no numeric conversions ({} to {})",
                    self.type_name(source),
                    self.type_name(target)
                ),
                Some(span),
            )]);
        }
        let kind = select_cast_kind(self.types, source, target, self.target).ok_or_else(|| {
            vec![Diagnostic::new(
                "E0230",
                Phase::Semantic,
                DiagnosticCategory::Conversion,
                format!(
                    "invalid explicit scalar conversion from {} to {}",
                    self.type_name(source),
                    self.type_name(target)
                ),
                Some(span),
            )]
        })?;
        let constant = operand
            .constant
            .map(|value| convert_constant(self.types, value, target, self.target, span))
            .transpose()?;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::ExplicitCast {
                    kind,
                    source_type: source,
                    target_type: target,
                    operand: Box::new(operand.expr),
                },
                ty: target,
                span,
            },
            constant,
        })
    }
    fn call(
        &mut self,
        n: &str,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if let Some(diagnostic) = self.invalid_default_reference(n, span) {
            return Err(diagnostic);
        }
        if let Some(local) = self.lookup(n) {
            if !type_arguments.is_empty() {
                return Err(vec![Diagnostic::new(
                    "E0353",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    "function values do not accept generic call arguments",
                    Some(span),
                )]);
            }
            let declared = self.locals[local.0 as usize].ty;
            let signature = if let Some(payload) = self.types.nullable_payload(declared) {
                if self.null_states.get(&local) != Some(&NullState::NonNull) {
                    return Err(vec![Diagnostic::new(
                        "E0455",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        "call requires a non-null function value",
                        Some(span),
                    )]);
                }
                payload
            } else {
                declared
            };
            let Some((parameters, result)) = self.types.function_signature(signature) else {
                return Err(vec![Diagnostic::new(
                    "E0215",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "value `{n}` of type {} is not callable",
                        self.type_name(signature)
                    ),
                    Some(span),
                )]);
            };
            let parameters = parameters.to_vec();
            if args.len() != parameters.len() {
                return Err(vec![Diagnostic::new(
                    if args.len() < parameters.len() {
                        "E0366"
                    } else {
                        "E0352"
                    },
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    if args.len() < parameters.len() {
                        format!(
                            "function value requires {} arguments; defaults are available only on direct declarations",
                            parameters.len()
                        )
                    } else {
                        format!(
                            "function value expects {} arguments, found {}",
                            parameters.len(),
                            args.len()
                        )
                    },
                    Some(span),
                )]);
            }
            let call_site = self.call_site();
            let mut checked = Vec::with_capacity(args.len());
            for (index, (argument, parameter)) in args.iter().zip(&parameters).enumerate() {
                checked.push(
                    self.adapt_call_argument(
                        argument,
                        *parameter,
                        call_site,
                        u32::try_from(index).expect("argument index fits u32"),
                        None,
                    )
                    .map_err(|mut diagnostics| {
                        if let Some(diagnostic) = diagnostics.first_mut() {
                            diagnostic.code = "E0353";
                            diagnostic.message = format!(
                                "indirect call argument {} is incompatible with signature: {}",
                                index + 1,
                                diagnostic.message
                            );
                        }
                        diagnostics
                    })?,
                );
            }
            if parameters.iter().any(|parameter| {
                self.types
                    .reference_info(*parameter)
                    .is_some_and(|(_, mutable)| mutable)
            }) {
                self.invalidate_nullable_aliases_after_mutating_call();
            }
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::IndirectCall {
                        call_site,
                        callee: Box::new(if declared == signature {
                            HirExpr {
                                kind: HirExprKind::Local(local),
                                ty: signature,
                                span,
                            }
                        } else {
                            HirExpr {
                                kind: HirExprKind::NullablePayload {
                                    source: HirPlace {
                                        base: HirPlaceBase::Local(local),
                                        projections: Vec::new(),
                                        ty: declared,
                                    },
                                    proof: self.fresh_non_null_proof(),
                                    access: NullablePayloadAccess::Copy,
                                },
                                ty: signature,
                                span,
                            }
                        }),
                        args: checked,
                        signature,
                    },
                    ty: result,
                    span,
                },
                constant: None,
            });
        }
        if let Some(id) = self.names[self.module.0 as usize].get(n).copied() {
            return self.call_id(id, n, type_arguments, args, span);
        }
        if let Some(symbol) = crate::prelude_symbol(n) {
            return self.core_call(symbol, type_arguments, args, span, expected);
        }
        Err(vec![Diagnostic::new(
            "E0212",
            Phase::Semantic,
            DiagnosticCategory::Name,
            format!("unknown function `{n}`"),
            Some(span),
        )])
    }

    fn core_call(
        &mut self,
        symbol: crate::CoreSymbol,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if !type_arguments.is_empty() {
            return Err(vec![type_error(
                format!(
                    "Core function `{}` does not accept type arguments",
                    symbol.member()
                ),
                span,
            )]);
        }
        let arity = crate::CoreFunction::resolve(symbol, TypeId::BOOL).arity();
        if args.len() != arity {
            return Err(vec![type_error(
                format!(
                    "Core function `{}` expects {arity} arguments, found {}",
                    symbol.member(),
                    args.len()
                ),
                span,
            )]);
        }
        if matches!(
            symbol,
            crate::CoreSymbol::Print | crate::CoreSymbol::Println
        ) {
            return Err(vec![type_error(
                "print/println are output effects and cannot be used as values",
                span,
            )]);
        }
        if symbol == crate::CoreSymbol::ByteLength {
            let argument = self.string_borrow_operand(&args[0])?;
            let function = crate::CoreFunction::resolve(symbol, TypeId::STRING);
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Core(Box::new(crate::CoreCall {
                            function,
                            arguments: vec![argument],
                        })),
                        ty: TypeId::USIZE,
                        span,
                    },
                    constant: None,
                },
                expected,
            );
        }
        if symbol == crate::CoreSymbol::Str {
            let argument = self.expression(&args[0], None)?.expr;
            if !matches!(
                self.types.get(argument.ty),
                Some(TypeData::Bool | TypeData::Char | TypeData::Integer(_) | TypeData::Float(_))
            ) {
                return Err(vec![type_error(
                    format!(
                        "Core function `str` has no v1 signature for {}",
                        self.type_name(argument.ty)
                    ),
                    span,
                )]);
            }
            let parameter_type = argument.ty;
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Core(Box::new(crate::CoreCall {
                            function: crate::CoreFunction::resolve(symbol, parameter_type),
                            arguments: vec![argument],
                        })),
                        ty: TypeId::STRING,
                        span,
                    },
                    constant: None,
                },
                expected,
            );
        }

        let contextual = expected.filter(|ty| self.types.is_numeric(*ty));
        let all_literals = args.iter().all(literal);
        let mut checked = Vec::with_capacity(args.len());
        for argument in args {
            checked.push(self.expression(argument, all_literals.then_some(contextual).flatten())?);
        }
        let mut parameter_type = checked[0].expr.ty;
        for argument in checked.iter().skip(1) {
            parameter_type =
                common(self.types, parameter_type, argument.expr.ty).ok_or_else(|| {
                    vec![conversion_error(
                        self.types,
                        self.structs,
                        self.enums,
                        parameter_type,
                        argument.expr.ty,
                        span,
                    )]
                })?;
        }
        let signature_valid = match symbol {
            crate::CoreSymbol::Abs => {
                self.types
                    .integer_info(parameter_type)
                    .is_some_and(IntegerType::is_signed)
                    || self.types.float_info(parameter_type).is_some()
            }
            crate::CoreSymbol::Min | crate::CoreSymbol::Max | crate::CoreSymbol::Clamp => {
                self.types.is_numeric(parameter_type)
            }
            crate::CoreSymbol::Sqrt
            | crate::CoreSymbol::Exp
            | crate::CoreSymbol::Ln
            | crate::CoreSymbol::Sin
            | crate::CoreSymbol::Cos
            | crate::CoreSymbol::Tan => self.types.float_info(parameter_type).is_some(),
            crate::CoreSymbol::Print
            | crate::CoreSymbol::Println
            | crate::CoreSymbol::ByteLength
            | crate::CoreSymbol::Str => unreachable!(),
        };
        if !signature_valid {
            return Err(vec![type_error(
                format!(
                    "Core function `{}` has no v1 signature for {}",
                    symbol.member(),
                    self.type_name(parameter_type)
                ),
                span,
            )]);
        }
        let arguments = checked
            .into_iter()
            .map(|argument| self.coerce(argument, Some(parameter_type)).map(|c| c.expr))
            .collect::<Result<Vec<_>, _>>()?;
        let function = crate::CoreFunction::resolve(symbol, parameter_type);
        self.coerce(
            Checked {
                expr: HirExpr {
                    kind: HirExprKind::Core(Box::new(crate::CoreCall {
                        function,
                        arguments,
                    })),
                    ty: parameter_type,
                    span,
                },
                constant: None,
            },
            expected,
        )
    }
    fn local_enum_id(&self, name: &str) -> Option<EnumId> {
        self.aliases[self.module.0 as usize]
            .get(name)
            .copied()
            .and_then(|ty| self.types.enum_id(ty))
            .or_else(|| self.enum_names[self.module.0 as usize].get(name).copied())
    }

    fn qualified_enum_type(
        &mut self,
        module: &str,
        name: &str,
        arguments: &[AstType],
        span: Span,
    ) -> Result<TypeId, Vec<Diagnostic>> {
        let ty = AstType {
            kind: crate::AstTypeKind::Named {
                module: Some(module.into()),
                name: name.into(),
                arguments: arguments.to_vec(),
            },
            span,
        };
        let resolved = self.resolve_source_type(&ty)?;
        self.types
            .enum_id(resolved)
            .map(|_| resolved)
            .ok_or_else(|| {
                vec![Diagnostic::new(
                    "E0250",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!("`{module}.{name}` is not an enum"),
                    Some(span),
                )]
            })
    }
    fn qualified_apply(
        &mut self,
        m: &str,
        f: &str,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let Some(mid) = self.imports[self.module.0 as usize].get(m).copied() else {
            let known = self.module_names.contains_key(m);
            return Err(vec![Diagnostic::new(
                if known { "E0223" } else { "E0221" },
                Phase::Semantic,
                DiagnosticCategory::Name,
                if known {
                    format!("package `{m}` is not imported")
                } else {
                    format!("unknown package path or namespace alias `{m}`")
                },
                Some(span),
            )]);
        };
        self.used_modules.insert(mid);
        if self.module_names.get("std.Text") == Some(&mid) {
            return self.text_apply(mid, f, type_arguments, args, span);
        }
        if let Some(id) = self.names[mid.0 as usize].get(f).copied() {
            return self.call_id(id, &format!("{m}.{f}"), type_arguments, args, span);
        }
        if let Some(id) = self.struct_names[mid.0 as usize].get(f).copied() {
            let resolved = self.resolve_type_arguments(type_arguments)?;
            let ty = self.nominal_struct_type(id, resolved, span)?;
            return self.struct_init(ty, &format!("{m}.{f}"), args, span);
        }
        if let Some(ty) = self.aliases[mid.0 as usize].get(f).copied()
            && self.types.struct_id(ty).is_some()
        {
            if !type_arguments.is_empty() {
                return Err(vec![generic_call_arity(f, 0, type_arguments.len(), span)]);
            }
            return self.struct_init(ty, &format!("{m}.{f}"), args, span);
        }
        Err(vec![Diagnostic::new(
            "E0222",
            Phase::Semantic,
            DiagnosticCategory::Name,
            format!("unknown function or struct `{f}` in module `{m}`"),
            Some(span),
        )])
    }

    fn text_apply(
        &mut self,
        module: ModuleId,
        function: &str,
        type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if !type_arguments.is_empty() {
            return Err(vec![type_error(
                "Text functions do not accept type arguments",
                span,
            )]);
        }
        let scalar_id = self.struct_names[module.0 as usize]
            .get("ScalarOffset")
            .copied()
            .ok_or_else(|| {
                vec![type_error(
                    "canonical Text.ScalarOffset is unavailable",
                    span,
                )]
            })?;
        let scalar_ty = self.types.intern(TypeData::Struct(scalar_id));
        let find_id = self.enum_names[module.0 as usize]
            .get("FindResult")
            .copied()
            .ok_or_else(|| vec![type_error("canonical Text.FindResult is unavailable", span)])?;
        let find_ty = self.types.intern(TypeData::Enum(find_id));
        let byte_slice_id = self.enum_names[module.0 as usize]
            .get("ByteSliceResult")
            .copied()
            .ok_or_else(|| {
                vec![type_error(
                    "canonical Text.ByteSliceResult is unavailable",
                    span,
                )]
            })?;
        let byte_slice_ty = self.types.intern(TypeData::Enum(byte_slice_id));
        let arity = match function {
            "scalarOffset" | "codePointCount" | "trim" | "lines" | "parseInt" | "parseDouble" => 1,
            "contains" | "startsWith" | "endsWith" | "find" | "split" | "byteAt"
            | "isByteBoundary" => 2,
            "findFrom" | "substring" | "byteSlice" => 3,
            _ => {
                return Err(vec![Diagnostic::new(
                    "E0222",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("unknown function `{function}` in module `Text`"),
                    Some(span),
                )]);
            }
        };
        if args.len() != arity {
            return Err(vec![type_error(
                format!(
                    "Text.{function} expects {arity} arguments, found {}",
                    args.len()
                ),
                span,
            )]);
        }
        if function == "scalarOffset" {
            return self.struct_init(scalar_ty, "Text.scalarOffset", args, span);
        }
        let call_site = self.call_site();
        let string_ref = self.types.intern_reference(TypeId::STRING, false);
        let mut adapted = Vec::with_capacity(args.len());
        let string_count = match function {
            "codePointCount" | "trim" | "substring" | "lines" | "byteAt" | "isByteBoundary"
            | "byteSlice" | "parseInt" | "parseDouble" => 1,
            "contains" | "startsWith" | "endsWith" | "find" | "findFrom" | "split" => 2,
            _ => unreachable!(),
        };
        for (index, argument) in args.iter().enumerate() {
            let parameter = if index < string_count {
                string_ref
            } else if matches!(function, "byteAt" | "isByteBoundary" | "byteSlice") {
                TypeId::USIZE
            } else {
                scalar_ty
            };
            adapted.push(self.adapt_call_argument(
                argument,
                parameter,
                call_site,
                u32::try_from(index).expect("argument index fits u32"),
                None,
            )?);
        }
        let (op, ty) = match function {
            "codePointCount" => (
                crate::TextOp::CodePointCount {
                    value: adapted[0].clone(),
                },
                TypeId::USIZE,
            ),
            "contains" => (
                crate::TextOp::Contains {
                    value: adapted[0].clone(),
                    needle: adapted[1].clone(),
                },
                TypeId::BOOL,
            ),
            "startsWith" => (
                crate::TextOp::StartsWith {
                    value: adapted[0].clone(),
                    prefix: adapted[1].clone(),
                },
                TypeId::BOOL,
            ),
            "endsWith" => (
                crate::TextOp::EndsWith {
                    value: adapted[0].clone(),
                    suffix: adapted[1].clone(),
                },
                TypeId::BOOL,
            ),
            "find" => (
                crate::TextOp::Find {
                    value: adapted[0].clone(),
                    needle: adapted[1].clone(),
                    start: None,
                },
                find_ty,
            ),
            "findFrom" => (
                crate::TextOp::Find {
                    value: adapted[0].clone(),
                    needle: adapted[1].clone(),
                    start: Some(adapted[2].clone()),
                },
                find_ty,
            ),
            "substring" => (
                crate::TextOp::Substring {
                    value: adapted[0].clone(),
                    start: adapted[1].clone(),
                    end: adapted[2].clone(),
                },
                TypeId::STRING,
            ),
            "trim" => (
                crate::TextOp::Trim {
                    value: adapted[0].clone(),
                },
                TypeId::STRING,
            ),
            "split" => {
                let list = self.types.intern_list(TypeId::STRING);
                (
                    crate::TextOp::Split {
                        value: adapted[0].clone(),
                        separator: adapted[1].clone(),
                    },
                    list,
                )
            }
            "lines" => {
                let list = self.types.intern_list(TypeId::STRING);
                (
                    crate::TextOp::Lines {
                        value: adapted[0].clone(),
                    },
                    list,
                )
            }
            "byteAt" => (
                crate::TextOp::ByteAt {
                    value: adapted[0].clone(),
                    offset: adapted[1].clone(),
                },
                TypeId::UINT8,
            ),
            "isByteBoundary" => (
                crate::TextOp::IsByteBoundary {
                    value: adapted[0].clone(),
                    offset: adapted[1].clone(),
                },
                TypeId::BOOL,
            ),
            "byteSlice" => (
                crate::TextOp::ByteSlice {
                    value: adapted[0].clone(),
                    start: adapted[1].clone(),
                    end_exclusive: adapted[2].clone(),
                },
                byte_slice_ty,
            ),
            "parseInt" => {
                let result = self.enum_names[module.0 as usize]
                    .get("IntParseResult")
                    .copied()
                    .ok_or_else(|| {
                        vec![type_error(
                            "canonical Text.IntParseResult is unavailable",
                            span,
                        )]
                    })?;
                (
                    crate::TextOp::ParseInt {
                        value: adapted[0].clone(),
                    },
                    self.types.intern(TypeData::Enum(result)),
                )
            }
            "parseDouble" => {
                let result = self.enum_names[module.0 as usize]
                    .get("DoubleParseResult")
                    .copied()
                    .ok_or_else(|| {
                        vec![type_error(
                            "canonical Text.DoubleParseResult is unavailable",
                            span,
                        )]
                    })?;
                (
                    crate::TextOp::ParseDouble {
                        value: adapted[0].clone(),
                    },
                    self.types.intern(TypeData::Enum(result)),
                )
            }
            _ => unreachable!(),
        };
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Text {
                    call_site,
                    op: Box::new(op),
                },
                ty,
                span,
            },
            constant: None,
        })
    }

    fn struct_init(
        &mut self,
        ty: TypeId,
        spelling: &str,
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let id = self
            .types
            .struct_id(ty)
            .expect("resolved struct initializer");
        let info = self.structs[id.0 as usize].clone();
        if args.len() != info.fields.len() {
            return Err(vec![Diagnostic::new(
                "E0246",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "struct `{spelling}` expects {} positional arguments, found {}",
                    info.fields.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut fields = Vec::with_capacity(args.len());
        for (index, (argument, field)) in args.iter().zip(&info.fields).enumerate() {
            let field_ty = self.specialize_member_type(ty, field.ty)?;
            match self.expression(argument, Some(field_ty)) {
                Ok(value) => fields.push((field.id, value.expr)),
                Err(mut diagnostics) => {
                    if let Some(diagnostic) = diagnostics.first_mut() {
                        diagnostic.code = "E0247";
                        diagnostic.message = format!(
                            "argument {} for field `{}` of `{spelling}` requires {}: {}",
                            index + 1,
                            field.name,
                            self.type_name(field_ty),
                            diagnostic.message
                        );
                    }
                    return Err(diagnostics);
                }
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::StructInit {
                    struct_id: id,
                    fields,
                },
                ty,
                span,
            },
            constant: None,
        })
    }
    fn enum_init(
        &mut self,
        ty: TypeId,
        variant_name: &str,
        args: &[AstExpr],
        parenthesized: bool,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let id = self.types.enum_id(ty).expect("resolved enum initializer");
        let info = self.enums[id.0 as usize].clone();
        let Some(variant_id) = self.variant_names[id.0 as usize].get(variant_name).copied() else {
            return Err(vec![Diagnostic::new(
                "E0252",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown variant `{variant_name}` on enum `{}`", info.name),
                Some(span),
            )]);
        };
        let variant = &info.variants[variant_id.index as usize];
        if parenthesized == variant.payloads.is_empty() {
            return Err(vec![Diagnostic::new(
                "E0250",
                Phase::Semantic,
                DiagnosticCategory::Syntax,
                if parenthesized {
                    format!(
                        "payloadless variant `{}.{}` must be constructed without `()`",
                        info.name, variant.name
                    )
                } else {
                    format!(
                        "payload variant `{}.{}` requires parenthesized arguments",
                        info.name, variant.name
                    )
                },
                Some(span),
            )]);
        }
        if args.len() != variant.payloads.len() {
            return Err(vec![Diagnostic::new(
                "E0253",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "variant `{}.{}` expects {} payload arguments, found {}",
                    info.name,
                    variant.name,
                    variant.payloads.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut payloads = Vec::with_capacity(args.len());
        for (index, (argument, payload)) in args.iter().zip(&variant.payloads).enumerate() {
            let payload_ty = self.specialize_member_type(ty, payload.ty)?;
            match self.expression(argument, Some(payload_ty)) {
                Ok(value) => payloads.push(value.expr),
                Err(mut diagnostics) => {
                    if let Some(diagnostic) = diagnostics.first_mut() {
                        diagnostic.code = "E0254";
                        diagnostic.message = format!(
                            "payload {} of `{}.{}` requires {}: {}",
                            index + 1,
                            info.name,
                            variant.name,
                            self.type_name(payload_ty),
                            diagnostic.message
                        );
                    }
                    return Err(diagnostics);
                }
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::EnumInit {
                    enum_id: id,
                    variant_id,
                    payloads,
                },
                ty,
                span,
            },
            constant: None,
        })
    }
    fn call_id(
        &mut self,
        id: FunctionId,
        name: &str,
        source_type_arguments: &[AstType],
        args: &[AstExpr],
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let s = self.signatures[id.0 as usize].clone();
        let minimum_arity = s.minimum_arity();
        if args.len() < minimum_arity {
            return Err(vec![Diagnostic::new(
                "E0362",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "function `{name}` accepts {minimum_arity}..{} arguments, found {}; missing required arguments",
                    s.parameters.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        if args.len() > s.parameters.len() {
            return Err(vec![Diagnostic::new(
                "E0363",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "function `{name}` accepts at most {} arguments, found {}",
                    s.parameters.len(),
                    args.len()
                ),
                args.get(s.parameters.len())
                    .map_or(Some(span), |arg| Some(arg.span)),
            )]);
        }
        let mut type_arguments = self.resolve_type_arguments(source_type_arguments)?;
        let mut prechecked = None;
        let inferred_application =
            source_type_arguments.is_empty() && !s.generic_parameters.is_empty();
        if inferred_application {
            let checked = args
                .iter()
                .zip(&s.parameters)
                .map(|(argument, parameter)| {
                    if matches!(argument.kind, AstExprKind::Null) {
                        return Ok(None);
                    }
                    let expected =
                        (!self.types.contains_generic(parameter.ty)).then_some(parameter.ty);
                    self.expression(argument, expected).map(Some)
                })
                .collect::<Result<Vec<_>, _>>()?;
            let mut inferred = BTreeMap::new();
            for (parameter, argument) in s.parameters.iter().zip(&checked) {
                if let Some(argument) = argument {
                    infer_generic_arguments(
                        self.types,
                        parameter.ty,
                        argument.expr.ty,
                        &mut inferred,
                    )?;
                }
            }
            for parameter in &s.generic_parameters {
                let Some(argument) = inferred.get(&parameter.id).copied() else {
                    return Err(vec![Diagnostic::new(
                        "E0263",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "cannot infer generic parameter `{}` for `{name}`",
                            parameter.name
                        ),
                        Some(span),
                    )]);
                };
                type_arguments.push(argument);
            }
            prechecked = Some(checked);
        }
        if type_arguments.len() != s.generic_parameters.len() {
            return Err(vec![generic_call_arity(
                name,
                s.generic_parameters.len(),
                type_arguments.len(),
                span,
            )]);
        }
        validate_generic_constraints(
            self.types,
            &s.generic_parameters,
            &type_arguments,
            name,
            self.structs,
            self.enums,
            span,
            inferred_application,
        )?;
        let substitution = Substitution::new(
            s.generic_parameters.iter().map(|parameter| parameter.id),
            type_arguments.iter().copied(),
        );
        let concrete_parameters = s
            .parameters
            .iter()
            .map(|parameter| self.types.substitute(parameter.ty, &substitution))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|parameter| vec![incomplete_substitution(parameter, span)])?;
        let return_type = self
            .types
            .substitute(s.return_type, &substitution)
            .map_err(|parameter| vec![incomplete_substitution(parameter, span)])?;
        let call_site = self.call_site();
        let mut out = Vec::with_capacity(s.parameters.len());
        for (index, concrete_ty) in concrete_parameters.iter().copied().enumerate() {
            let argument_index = u32::try_from(index).expect("argument index fits u32");
            let (initializer, origin) = if let Some(argument) = args.get(index) {
                let checked = prechecked.as_ref().and_then(|values| values[index].clone());
                let initializer = self
                    .adapt_call_argument(argument, concrete_ty, call_site, argument_index, checked)
                    .map_err(|mut diagnostics| {
                        if let Some(diagnostic) = diagnostics.first_mut() {
                            diagnostic.code = "E0214";
                            diagnostic.message = format!(
                                "argument {} to `{name}` requires {}: {}",
                                index + 1,
                                self.type_name(concrete_ty),
                                diagnostic.message
                            );
                        }
                        diagnostics
                    })?;
                (
                    initializer,
                    HirCallArgumentOrigin::Explicit {
                        source_span: argument.span,
                    },
                )
            } else {
                let template = s.parameters[index]
                    .default
                    .as_ref()
                    .expect("arity range guarantees a trailing default");
                let initializer = self.materialize_default_argument(
                    &s,
                    template,
                    concrete_ty,
                    &type_arguments,
                    &out,
                    call_site,
                    span,
                )?;
                (
                    initializer,
                    HirCallArgumentOrigin::Defaulted {
                        declaration: id,
                        parameter_index: argument_index,
                        default_span: template.expression.span,
                        call_span: span,
                    },
                )
            };
            let binding = LocalId(self.locals.len() as u32);
            self.locals.push(HirLocal {
                id: binding,
                name: format!("$call{}_arg{index}", call_site.0),
                ty: concrete_ty,
                span: initializer.span,
                parameter: false,
                source_binding: false,
                mutability: crate::BindingMutability::Mutable,
                address_taken: false,
            });
            out.push(HirCallArgument {
                binding,
                initializer,
                ty: concrete_ty,
                origin,
            });
        }
        if concrete_parameters.iter().any(|parameter| {
            self.types
                .reference_info(*parameter)
                .is_some_and(|(_, mutable)| mutable)
        }) {
            self.invalidate_nullable_aliases_after_mutating_call();
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Call {
                    call_site,
                    callee: HirCallTarget::Declaration(id),
                    type_arguments,
                    args: out,
                },
                ty: return_type,
                span,
            },
            constant: None,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn materialize_default_argument(
        &mut self,
        signature: &FunctionSignature,
        template: &DefaultArgumentTemplate,
        parameter_type: TypeId,
        type_arguments: &[TypeId],
        previous: &[HirCallArgument],
        call_site: CallSiteId,
        call_span: Span,
    ) -> Result<HirExpr, Vec<Diagnostic>> {
        let index = template.parameter_index as usize;
        let scope = signature.parameters[..index]
            .iter()
            .zip(previous)
            .map(|(parameter, argument)| (parameter.name.clone(), argument.binding))
            .collect::<BTreeMap<_, _>>();
        let forbidden = signature.parameters[index..]
            .iter()
            .enumerate()
            .map(|(offset, parameter)| (parameter.name.clone(), offset == 0))
            .collect::<BTreeMap<_, _>>();
        let concrete_generics = signature
            .generic_parameters
            .iter()
            .zip(type_arguments)
            .map(|(parameter, argument)| (parameter.name.clone(), *argument))
            .collect::<BTreeMap<_, _>>();

        let saved_module = self.module;
        let saved_scopes = std::mem::replace(&mut self.scopes, vec![scope]);
        let saved_generics = std::mem::replace(&mut self.generic_scope, concrete_generics);
        let saved_class = self.class_method.take();
        let saved_context = self
            .default_forbidden
            .replace((signature.parameters[index].name.clone(), forbidden));
        self.module = signature.module;
        let result = self.adapt_call_argument(
            &template.expression,
            parameter_type,
            call_site,
            template.parameter_index,
            None,
        );
        self.module = saved_module;
        self.scopes = saved_scopes;
        self.generic_scope = saved_generics;
        self.class_method = saved_class;
        self.default_forbidden = saved_context;

        result.map_err(|mut diagnostics| {
            if let Some(diagnostic) = diagnostics.first_mut()
                && diagnostic.code != "E0364"
            {
                let cause = diagnostic.message.clone();
                diagnostic.code = if signature.generic_parameters.is_empty()
                    && matches!(
                        diagnostic.category,
                        DiagnosticCategory::Type | DiagnosticCategory::Conversion
                    ) {
                    "E0361"
                } else {
                    "E0365"
                };
                diagnostic.message = format!(
                    "default for parameter `{}` requires {}: {cause} (at call {}..{})",
                    signature.parameters[index].name,
                    self.type_name(parameter_type),
                    call_span.start,
                    call_span.end
                );
            }
            diagnostics
        })
    }

    fn adapt_call_argument(
        &mut self,
        source: &AstExpr,
        parameter_type: TypeId,
        call_site: CallSiteId,
        argument_index: u32,
        prechecked: Option<Checked>,
    ) -> Result<HirExpr, Vec<Diagnostic>> {
        let reference = self.types.reference_info(parameter_type);
        if let Some((pointee, false)) = reference
            && let AstExprKind::Name(name) = &source.kind
            && let Some(local) = self.lookup(name)
            && self.null_states.get(&local) == Some(&NullState::NonNull)
            && self
                .types
                .nullable_payload(self.locals[local.0 as usize].ty)
                == Some(pointee)
        {
            let declared = self.locals[local.0 as usize].ty;
            let proof = self.fresh_non_null_proof();
            return Ok(HirExpr {
                kind: HirExprKind::CallScopedSharedBorrow {
                    call_site,
                    argument_index,
                    pointee_type: pointee,
                    reference_type: parameter_type,
                    source: CallBorrowSource::Temporary(Box::new(HirExpr {
                        kind: HirExprKind::NullablePayload {
                            source: HirPlace {
                                base: HirPlaceBase::Local(local),
                                projections: Vec::new(),
                                ty: declared,
                            },
                            proof,
                            access: NullablePayloadAccess::Borrow,
                        },
                        ty: pointee,
                        span: source.span,
                    })),
                    origin: CallBorrowOrigin::Implicit,
                },
                ty: parameter_type,
                span: source.span,
            });
        }
        if let Some((pointee, false)) = reference
            && let Ok(place) = self.resolve_expr_place(source, false)
            && place.ty == pointee
        {
            self.mark_place_address_taken(&place);
            return Ok(HirExpr {
                kind: HirExprKind::CallScopedSharedBorrow {
                    call_site,
                    argument_index,
                    pointee_type: pointee,
                    reference_type: parameter_type,
                    source: CallBorrowSource::Place(place),
                    origin: CallBorrowOrigin::Implicit,
                },
                ty: parameter_type,
                span: source.span,
            });
        }
        let checked = if let Some(checked) = prechecked {
            checked
        } else if let Some((pointee, false)) = reference {
            if matches!(
                source.kind,
                AstExprKind::Unary {
                    op: AstUnaryOp::BorrowShared,
                    ..
                }
            ) || self
                .resolve_expr_place(source, false)
                .is_ok_and(|place| place.ty == parameter_type)
            {
                self.expression(source, Some(parameter_type))?
            } else {
                self.expression(source, Some(pointee))?
            }
        } else if reference.is_some_and(|(_, mutable)| mutable)
            && !matches!(
                source.kind,
                AstExprKind::Unary {
                    op: AstUnaryOp::BorrowMutable,
                    ..
                }
            )
        {
            self.expression(source, None)?
        } else {
            self.expression(source, Some(parameter_type))?
        };

        if checked.expr.ty == parameter_type {
            if let (
                Some((pointee, false)),
                HirExprKind::Borrow {
                    place,
                    mutable: false,
                },
            ) = (reference, &checked.expr.kind)
            {
                return Ok(HirExpr {
                    kind: HirExprKind::CallScopedSharedBorrow {
                        call_site,
                        argument_index,
                        pointee_type: pointee,
                        reference_type: parameter_type,
                        source: CallBorrowSource::Place(place.clone()),
                        origin: CallBorrowOrigin::Explicit,
                    },
                    ty: parameter_type,
                    span: checked.expr.span,
                });
            }
            return Ok(checked.expr);
        }

        if let Some((pointee, false)) = reference {
            if checked.expr.ty == pointee
                && !matches!(checked.expr.kind, HirExprKind::Coerce { .. })
            {
                return Ok(HirExpr {
                    kind: HirExprKind::CallScopedSharedBorrow {
                        call_site,
                        argument_index,
                        pointee_type: pointee,
                        reference_type: parameter_type,
                        source: CallBorrowSource::Temporary(Box::new(checked.expr)),
                        origin: CallBorrowOrigin::Implicit,
                    },
                    ty: parameter_type,
                    span: source.span,
                });
            }
            return Err(vec![type_error(
                format!(
                    "implicit shared argument borrow requires exact {}; found {}",
                    self.type_name(pointee),
                    self.type_name(checked.expr.ty)
                ),
                source.span,
            )]);
        }
        if reference.is_some_and(|(_, mutable)| mutable) {
            return Err(vec![type_error(
                "implicit mutable argument borrows are not supported; use `&mut place`",
                source.span,
            )]);
        }
        self.coerce(checked, Some(parameter_type))
            .map(|value| value.expr)
    }

    fn mark_place_address_taken(&mut self, place: &HirPlace) {
        if let HirPlaceBase::Local(local) = place.base
            && !place
                .projections
                .iter()
                .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
        {
            self.locals[local.0 as usize].address_taken = true;
        }
    }
    // Operand places are borrowed before ordinary value resolution can insert Move.
    // This preserves projected owners and explicit dereferences as well as locals.
    fn readable_math_operand(
        &mut self,
        expr: &AstExpr,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if let Ok(source) = self.resolve_expr_place(expr, false) {
            if self.types.vector_like_info(source.ty).is_some() {
                return self.vector_view_from_place(source, false, false, expr.span, None);
            }
            if let Some(element) = self.types.matrix_like_element(source.ty) {
                let descriptor = crate::types::MatrixViewDescriptor::derived(
                    self.types.matrix_view_info(source.ty).is_some(),
                    false,
                );
                let ty = self.types.intern_matrix_view(element, false);
                return Ok(Checked {
                    expr: HirExpr {
                        kind: HirExprKind::MatrixView {
                            source,
                            mutable: false,
                            transpose: false,
                            descriptor,
                        },
                        ty,
                        span: expr.span,
                    },
                    constant: None,
                });
            }
        }
        self.expression(expr, expected)
    }

    fn literal_binary_context(&self, op: AstBinaryOp, ty: TypeId) -> Option<TypeId> {
        if op == AstBinaryOp::Multiply {
            if let Some((element, _)) = self.types.vector_like_info(ty) {
                return self
                    .types
                    .supports_builtin_multiply(element)
                    .then_some(element);
            }
            if let Some(element) = self.types.matrix_like_element(ty) {
                return self
                    .types
                    .supports_builtin_multiply(element)
                    .then_some(element);
            }
        }
        self.types.is_numeric(ty).then_some(ty)
    }

    fn binary(
        &mut self,
        op: AstBinaryOp,
        la: &AstExpr,
        ra: &AstExpr,
        expected: Option<TypeId>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        if matches!(op, AstBinaryOp::LogicalAnd | AstBinaryOp::LogicalOr) {
            let left = self.expression(la, Some(TypeId::BOOL))?.expr;
            let saved = self.null_states.clone();
            self.refine_for_condition(la, op == AstBinaryOp::LogicalAnd);
            let right = self.expression(ra, Some(TypeId::BOOL))?.expr;
            self.null_states = saved;
            let kind = if op == AstBinaryOp::LogicalAnd {
                HirExprKind::ShortCircuitAnd {
                    left: Box::new(left),
                    right: Box::new(right),
                }
            } else {
                HirExprKind::ShortCircuitOr {
                    left: Box::new(left),
                    right: Box::new(right),
                }
            };
            return Ok(Checked {
                expr: HirExpr {
                    kind,
                    ty: TypeId::BOOL,
                    span,
                },
                constant: None,
            });
        }
        if matches!(
            op,
            AstBinaryOp::Equal
                | AstBinaryOp::NotEqual
                | AstBinaryOp::Less
                | AstBinaryOp::LessEqual
                | AstBinaryOp::Greater
                | AstBinaryOp::GreaterEqual
        ) && !matches!(la.kind, AstExprKind::Null)
            && !matches!(ra.kind, AstExprKind::Null)
            && [la, ra].into_iter().any(|operand| {
                let AstExprKind::Name(name) = &operand.kind else {
                    return false;
                };
                self.lookup(name).is_some_and(|local| {
                    self.types
                        .nullable_payload(self.locals[local.0 as usize].ty)
                        .is_some()
                })
            })
        {
            return Err(vec![type_error(
                "general nullable equality and ordering are not supported; compare the value with null",
                span,
            )]);
        }
        if matches!(op, AstBinaryOp::Equal | AstBinaryOp::NotEqual)
            && (matches!(la.kind, AstExprKind::Null) || matches!(ra.kind, AstExprKind::Null))
        {
            if matches!(la.kind, AstExprKind::Null) && matches!(ra.kind, AstExprKind::Null) {
                return Ok(Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Bool(op == AstBinaryOp::Equal),
                        ty: TypeId::BOOL,
                        span,
                    },
                    constant: None,
                });
            }
            let other = if matches!(la.kind, AstExprKind::Null) {
                ra
            } else {
                la
            };
            let operand = if let AstExprKind::Name(name) = &other.kind {
                let local = self
                    .lookup(name)
                    .ok_or_else(|| vec![unknown_name(name, other.span)])?;
                let ty = self.locals[local.0 as usize].ty;
                if self.types.nullable_payload(ty).is_none() {
                    return Err(vec![type_error(
                        "null comparison requires a nullable operand",
                        span,
                    )]);
                }
                HirExpr {
                    kind: HirExprKind::Local(local),
                    ty,
                    span: other.span,
                }
            } else {
                let checked = self.expression(other, None)?.expr;
                if self.types.nullable_payload(checked.ty).is_none() {
                    return Err(vec![type_error(
                        "null comparison requires a nullable operand",
                        span,
                    )]);
                }
                checked
            };
            let is_null = HirExpr {
                kind: HirExprKind::NullableIsNull {
                    operand: Box::new(operand),
                },
                ty: TypeId::BOOL,
                span,
            };
            let expr = if op == AstBinaryOp::Equal {
                is_null
            } else {
                HirExpr {
                    kind: HirExprKind::LogicalNot {
                        operand: Box::new(is_null),
                    },
                    ty: TypeId::BOOL,
                    span,
                }
            };
            return Ok(Checked {
                expr,
                constant: None,
            });
        }
        if expected == Some(TypeId::STRING) || self.ast_is_string(la) || self.ast_is_string(ra) {
            if !matches!(
                op,
                AstBinaryOp::Add | AstBinaryOp::Equal | AstBinaryOp::NotEqual
            ) {
                return Err(vec![type_error(
                    "string admits only +, == and != in GENERAL-V1",
                    span,
                )]);
            }
            let left = self.string_borrow_operand(la)?;
            let right = self.string_borrow_operand(ra)?;
            let (kind, ty) = if op == AstBinaryOp::Add {
                (crate::StringOp::Concat { left, right }, TypeId::STRING)
            } else {
                (
                    crate::StringOp::Equal {
                        left,
                        right,
                        negate: op == AstBinaryOp::NotEqual,
                    },
                    TypeId::BOOL,
                )
            };
            return self.coerce(
                Checked {
                    expr: HirExpr {
                        kind: HirExprKind::String(Box::new(kind)),
                        ty,
                        span,
                    },
                    constant: None,
                },
                expected,
            );
        }
        let ll = literal(la);
        let rl = literal(ra);
        let (l, r) = if ll && !rl {
            let r = self.readable_math_operand(ra, None)?;
            (
                self.readable_math_operand(la, self.literal_binary_context(op, r.expr.ty))?,
                r,
            )
        } else if rl && !ll {
            let l = self.readable_math_operand(la, None)?;
            let r = self.readable_math_operand(ra, self.literal_binary_context(op, l.expr.ty))?;
            (l, r)
        } else if ll && rl {
            let c = expected.filter(|t| self.types.is_numeric(*t));
            (
                self.readable_math_operand(la, c)?,
                self.readable_math_operand(ra, c)?,
            )
        } else {
            (
                self.readable_math_operand(la, None)?,
                self.readable_math_operand(ra, None)?,
            )
        };
        if self.types.interface_id(l.expr.ty).is_some()
            || self.types.interface_id(r.expr.ty).is_some()
        {
            return Err(vec![classes::error(
                "E0414",
                "interface operators are not admitted",
                span,
            )]);
        }
        let lv = self.types.vector_like_info(l.expr.ty);
        let rv = self.types.vector_like_info(r.expr.ty);
        let lm = self.types.matrix_like_element(l.expr.ty);
        let rm = self.types.matrix_like_element(r.expr.ty);
        if lv.is_some() || rv.is_some() || lm.is_some() || rm.is_some() {
            let symbol = match op {
                AstBinaryOp::Add => "+",
                AstBinaryOp::Subtract => "-",
                AstBinaryOp::Multiply => "*",
                AstBinaryOp::Divide => "/",
                _ => "unsupported binary operator",
            };
            let error = |code, reason: &str| {
                vec![Diagnostic::new(
                    code,
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "operator {symbol} on {} and {}: {reason}",
                        self.type_name(l.expr.ty),
                        self.type_name(r.expr.ty)
                    ),
                    Some(span),
                )]
            };
            if op == AstBinaryOp::Multiply {
                return self.resolve_native_multiplication(l, r, span);
            }
            if !matches!(op, AstBinaryOp::Add | AstBinaryOp::Subtract) {
                return Err(error(
                    "E0342",
                    "expected built-in elementwise +/− or scalar * vector-like/matrix-like",
                ));
            }
            let (element, orientation) = match (lv, rv, lm, rm) {
                (Some((a, ao)), Some((b, bo)), _, _) => {
                    if ao != bo {
                        return Err(error("E0344", "Row/Column orientation must match exactly"));
                    }
                    if a != b {
                        return Err(error(
                            "E0343",
                            "canonical element types must match exactly; no promotion",
                        ));
                    }
                    (a, Some(ao))
                }
                (_, _, Some(a), Some(b)) => {
                    if a != b {
                        return Err(error(
                            "E0343",
                            "canonical element types must match exactly; no promotion",
                        ));
                    }
                    (a, None)
                }
                _ => {
                    return Err(error(
                        "E0342",
                        "Vector/Matrix/scalar families cannot be mixed",
                    ));
                }
            };
            let behavior = if op == AstBinaryOp::Add {
                BehavioralCapability::Add
            } else {
                BehavioralCapability::Sub
            };
            let scalar_op = math_element_op(self.types, element, behavior)
                .map_err(|reason| error("E0346", &reason))?;
            // Intern readable descriptors for expression-owned temporaries as well.
            let (ty, kind) = if let Some(orientation) = orientation {
                self.types.intern_vector_view(element, orientation, false);
                (
                    self.types.intern_vector(element, orientation),
                    HirExprKind::VectorElementwiseBinary {
                        shape_check: MathShapeCheck::VectorDimension,
                        op: scalar_op,
                        source_op: op,
                        left: Box::new(l.expr),
                        right: Box::new(r.expr),
                        element_type: element,
                        orientation,
                    },
                )
            } else {
                self.types.intern_matrix_view(element, false);
                (
                    self.types.intern_matrix(element),
                    HirExprKind::MatrixElementwiseBinary {
                        shape_check: MathShapeCheck::MatrixRowsThenColumns,
                        op: scalar_op,
                        source_op: op,
                        left: Box::new(l.expr),
                        right: Box::new(r.expr),
                        element_type: element,
                    },
                )
            };
            return Ok(Checked {
                expr: HirExpr { kind, ty, span },
                constant: None,
            });
        }
        let equality = matches!(op, AstBinaryOp::Equal | AstBinaryOp::NotEqual);
        if self.types.enum_id(l.expr.ty).is_some() || self.types.enum_id(r.expr.ty).is_some() {
            if !equality {
                return Err(vec![Diagnostic::new(
                    "E0472",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "enum equality requires == or != on two values of the same enum type; found {} and {}",
                        self.type_name(l.expr.ty),
                        self.type_name(r.expr.ty)
                    ),
                    Some(span),
                )]);
            }
            return match classify_enum_equality(l.expr.ty, r.expr.ty, self.enums, self.types) {
                EnumEqualityClassification::Admitted { .. } => {
                    Ok(bin_result(self.types, op, l, r, TypeId::BOOL, None))
                }
                EnumEqualityClassification::DifferentDeclarations { .. } => {
                    Err(vec![Diagnostic::new(
                        "E0470",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "cannot compare distinct enum types `{}` and `{}`; enum equality is nominal",
                            self.type_name(l.expr.ty),
                            self.type_name(r.expr.ty)
                        ),
                        Some(span),
                    )])
                }
                EnumEqualityClassification::PayloadBearing { enum_id } => {
                    Err(vec![Diagnostic::new(
                        "E0471",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "equality for payload-bearing enum `{}` is not supported in ENUM-EQUALITY-V1",
                            self.enums[enum_id.0 as usize].name
                        ),
                        Some(span),
                    )])
                }
                EnumEqualityClassification::DifferentInstances { .. }
                | EnumEqualityClassification::NotBothEnums
                | EnumEqualityClassification::InvalidMetadata => Err(vec![Diagnostic::new(
                    "E0472",
                    Phase::Semantic,
                    DiagnosticCategory::Type,
                    format!(
                        "enum equality requires two values of the same enum type; found `{}` and `{}`",
                        self.type_name(l.expr.ty),
                        self.type_name(r.expr.ty)
                    ),
                    Some(span),
                )]),
            };
        }
        if self.types.reference_info(l.expr.ty).is_some()
            || self.types.reference_info(r.expr.ty).is_some()
        {
            return Err(vec![Diagnostic::new(
                "E0279",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "reference arithmetic and reference identity comparison are not supported in Vertical-9",
                Some(span),
            )]);
        }
        if l.expr.ty == TypeId::BOOL || r.expr.ty == TypeId::BOOL {
            if l.expr.ty == TypeId::BOOL && r.expr.ty == TypeId::BOOL && equality {
                return Ok(bin_result(self.types, op, l, r, TypeId::BOOL, None));
            }
            return Err(vec![type_error(
                "bool cannot be used numerically or compared with a number",
                span,
            )]);
        }
        if self.types.struct_id(l.expr.ty).is_some() || self.types.struct_id(r.expr.ty).is_some() {
            return Err(vec![type_error(
                "struct values do not have implicit arithmetic or equality operators in Vertical-5",
                span,
            )]);
        }
        if self.types.generic_param(l.expr.ty).is_some()
            || self.types.generic_param(r.expr.ty).is_some()
        {
            let behavior = match op {
                AstBinaryOp::Add => Some(BehavioralCapability::Add),
                AstBinaryOp::Subtract => Some(BehavioralCapability::Sub),
                AstBinaryOp::Multiply => Some(BehavioralCapability::Mul),
                _ => None,
            };
            if let Some(behavior) = behavior {
                let ty = l.expr.ty;
                if ty != r.expr.ty {
                    return Err(vec![Diagnostic::new(
                        "E0347",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "capability {behavior} requires homogeneous T {} T -> T operands",
                            behavior.symbol()
                        ),
                        Some(span),
                    )]);
                }
                if !self.types.guarantees_behavior(ty, behavior) {
                    return Err(vec![Diagnostic::new(
                        "E0268",
                        Phase::Semantic,
                        DiagnosticCategory::Type,
                        format!(
                            "operator '{}' on generic parameter {} requires capability {behavior}",
                            behavior.symbol(),
                            self.type_name(ty)
                        ),
                        Some(span),
                    )]);
                }
                return Ok(Checked {
                    expr: HirExpr {
                        kind: HirExprKind::CapabilityBinary {
                            behavior,
                            left: Box::new(l.expr),
                            right: Box::new(r.expr),
                        },
                        ty,
                        span,
                    },
                    constant: None,
                });
            }
            return Err(vec![Diagnostic::new(
                "E0268",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "operation is unsupported on an unconstrained generic parameter",
                Some(span),
            )]);
        }
        let common = common(self.types, l.expr.ty, r.expr.ty).ok_or_else(|| {
            vec![conversion_error(
                self.types,
                self.structs,
                self.enums,
                l.expr.ty,
                r.expr.ty,
                span,
            )]
        })?;
        let l = self.coerce(l, Some(common))?;
        let r = self.coerce(r, Some(common))?;
        if matches!(op, AstBinaryOp::Remainder) && self.types.float_info(common).is_some() {
            return Err(vec![Diagnostic::new(
                "E0235",
                Phase::Semantic,
                DiagnosticCategory::Division,
                "floating `%` is not supported; `%` is the integer remainder operator",
                Some(span),
            )]);
        }
        let arithmetic = matches!(
            op,
            AstBinaryOp::Add
                | AstBinaryOp::Subtract
                | AstBinaryOp::Multiply
                | AstBinaryOp::Divide
                | AstBinaryOp::Remainder
        );
        let result = if arithmetic { common } else { TypeId::BOOL };
        let known_integer = self.types.integer_info(common).is_some()
            && arithmetic
            && l.constant.is_some()
            && r.constant.is_some();
        let constant = if let Some(integer) = self.types.integer_info(common) {
            const_bin(op, l.constant, r.constant, integer, span, self.target)?
        } else {
            None
        };
        if known_integer && constant.is_none() {
            return Err(vec![Diagnostic::new(
                "E0210",
                Phase::Semantic,
                DiagnosticCategory::Integer,
                format!("constant integer expression overflows {common}"),
                Some(span),
            )]);
        }
        if let Some(ConstantValue::Integer(v)) = constant {
            check_value(self.types, v, common, span, self.target)?
        }
        Ok(bin_result(self.types, op, l, r, result, constant))
    }

    fn ast_is_string(&self, expression: &AstExpr) -> bool {
        match &expression.kind {
            AstExprKind::String(_) => true,
            AstExprKind::Name(name) => self
                .lookup(name)
                .is_some_and(|local| self.locals[local.0 as usize].ty == TypeId::STRING),
            AstExprKind::Binary {
                op: AstBinaryOp::Add,
                left,
                right,
            } => self.ast_is_string(left) || self.ast_is_string(right),
            AstExprKind::Call { callee, .. } => self.names[self.module.0 as usize]
                .get(callee)
                .is_some_and(|id| self.signatures[id.0 as usize].return_type == TypeId::STRING),
            AstExprKind::QualifiedCall {
                module, function, ..
            } => self.imports[self.module.0 as usize]
                .get(module)
                .and_then(|target| self.names[target.0 as usize].get(function))
                .is_some_and(|id| self.signatures[id.0 as usize].return_type == TypeId::STRING),
            _ => false,
        }
    }

    fn string_borrow_operand(&mut self, expression: &AstExpr) -> Result<HirExpr, Vec<Diagnostic>> {
        if let AstExprKind::Name(name) = &expression.kind
            && let Some(local) = self.lookup(name)
            && self.null_states.get(&local) == Some(&NullState::NonNull)
            && self
                .types
                .nullable_payload(self.locals[local.0 as usize].ty)
                == Some(TypeId::STRING)
        {
            let declared = self.locals[local.0 as usize].ty;
            let proof = self.fresh_non_null_proof();
            return Ok(HirExpr {
                kind: HirExprKind::NullablePayload {
                    source: HirPlace {
                        base: HirPlaceBase::Local(local),
                        projections: Vec::new(),
                        ty: declared,
                    },
                    proof,
                    access: NullablePayloadAccess::Borrow,
                },
                ty: TypeId::STRING,
                span: expression.span,
            });
        }
        if let Ok(place) = self.resolve_expr_place(expression, false)
            && place.ty == TypeId::STRING
        {
            let kind = match place.base {
                HirPlaceBase::Local(local) if place.projections.is_empty() => {
                    HirExprKind::Local(local)
                }
                _ => HirExprKind::Load(place),
            };
            return Ok(HirExpr {
                kind,
                ty: TypeId::STRING,
                span: expression.span,
            });
        }
        let checked = self.expression(expression, Some(TypeId::STRING))?;
        let span = checked.expr.span;
        match checked.expr.kind {
            HirExprKind::String(op) => match *op {
                crate::StringOp::Alias { source } => Ok(source),
                other => Ok(HirExpr {
                    kind: HirExprKind::String(Box::new(other)),
                    ty: TypeId::STRING,
                    span,
                }),
            },
            _ => Ok(checked.expr),
        }
    }
    fn coerce(&self, c: Checked, expected: Option<TypeId>) -> Result<Checked, Vec<Diagnostic>> {
        let Some(to) = expected else { return Ok(c) };
        if c.expr.ty == to {
            return Ok(c);
        }
        if let Some(payload) = self.types.nullable_payload(to)
            && c.expr.ty == payload
        {
            let span = c.expr.span;
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::NullableInject {
                        payload: Box::new(c.expr),
                        nullable_type: to,
                    },
                    ty: to,
                    span,
                },
                constant: None,
            });
        }
        if let Some(payload) = self.types.nullable_payload(c.expr.ty)
            && payload == to
        {
            return Err(vec![Diagnostic::new(
                "E0452",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "cannot use {} where non-null {} is required; prove value != null on this path",
                    self.type_name(c.expr.ty),
                    self.type_name(to)
                ),
                Some(c.expr.span),
            )]);
        }
        if let (Some(source_class), Some(target_base)) =
            (self.types.class_id(c.expr.ty), self.types.class_id(to))
        {
            if let Ok(chain) = self.types.class_chain(source_class)
                && let Some(end) = chain.iter().position(|c| *c == target_base)
            {
                let span = c.expr.span;
                let (source, transfer) = match c.expr.kind {
                    HirExprKind::Class(op)
                        if matches!(op.as_ref(), ClassOp::HandleAlias { .. }) =>
                    {
                        let ClassOp::HandleAlias { source } = *op else {
                            unreachable!()
                        };
                        (source, false)
                    }
                    _ => (c.expr, true),
                };
                return Ok(Checked {
                    expr: HirExpr {
                        kind: HirExprKind::Class(Box::new(ClassOp::ClassUpcast {
                            source_class,
                            target_base,
                            path: chain[..=end].to_vec(),
                            source,
                            transfer,
                        })),
                        ty: to,
                        span,
                    },
                    constant: None,
                });
            }
        }
        if let (Some(class), Some(interface)) =
            (self.types.class_id(c.expr.ty), self.types.interface_id(to))
        {
            let w = self
                .types
                .witnesses()
                .iter()
                .find(|w| w.class == class && w.interface == interface)
                .ok_or_else(|| {
                    vec![classes::error(
                        "E0413",
                        "class has no declared conformance to target interface",
                        c.expr.span,
                    )]
                })?;
            let span = c.expr.span;
            let (source, transfer) = match c.expr.kind {
                HirExprKind::Class(op) if matches!(op.as_ref(), ClassOp::HandleAlias { .. }) => {
                    let ClassOp::HandleAlias { source } = *op else {
                        unreachable!()
                    };
                    (source, false)
                }
                _ => (c.expr, true),
            };
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::Class(Box::new(ClassOp::InterfaceAdapt {
                        class,
                        interface,
                        witness: w.id,
                        source,
                        transfer,
                    })),
                    ty: to,
                    span,
                },
                constant: None,
            });
        }
        let kind = match (self.types.get(c.expr.ty), self.types.get(to)) {
            (Some(TypeData::Integer(a)), Some(TypeData::Integer(b))) if a.can_widen_to(*b) => {
                if a.is_signed() {
                    CoercionKind::SignExtend
                } else {
                    CoercionKind::ZeroExtend
                }
            }
            (_, _) if c.expr.ty == TypeId::FLOAT32 && to == TypeId::FLOAT64 => {
                CoercionKind::FloatExtend
            }
            _ => {
                return Err(vec![conversion_error(
                    self.types,
                    self.structs,
                    self.enums,
                    c.expr.ty,
                    to,
                    c.expr.span,
                )]);
            }
        };
        let span = c.expr.span;
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Coerce {
                    kind,
                    operand: Box::new(c.expr),
                },
                ty: to,
                span,
            },
            constant: c.constant,
        })
    }
    fn lookup(&self, n: &str) -> Option<LocalId> {
        self.scopes.iter().rev().find_map(|s| s.get(n).copied())
    }

    fn const_inline_root(&self, place: &HirPlace) -> Option<LocalId> {
        let HirPlaceBase::Local(local) = place.base else {
            return None;
        };
        let info = &self.locals[local.0 as usize];
        if info.mutability != crate::BindingMutability::Const
            || place
                .projections
                .iter()
                .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
        {
            return None;
        }
        Some(local)
    }

    fn type_name(&self, ty: TypeId) -> String {
        format_type(self.types, ty, self.structs, self.enums)
    }
}

fn literal(e: &AstExpr) -> bool {
    matches!(e.kind, AstExprKind::Integer(_) | AstExprKind::Float(_))
        || matches!(&e.kind,AstExprKind::Unary{operand,..}if matches!(operand.kind,AstExprKind::Integer(_)|AstExprKind::Float(_)))
}
fn common(types: &TypeArena, a: TypeId, b: TypeId) -> Option<TypeId> {
    if a == b {
        return Some(a);
    }
    match (types.get(a), types.get(b)) {
        (Some(TypeData::Integer(x)), Some(TypeData::Integer(y))) if x.can_widen_to(*y) => Some(b),
        (Some(TypeData::Integer(x)), Some(TypeData::Integer(y))) if y.can_widen_to(*x) => Some(a),
        _ if a == TypeId::FLOAT32 && b == TypeId::FLOAT64 => Some(b),
        _ if a == TypeId::FLOAT64 && b == TypeId::FLOAT32 => Some(a),
        _ => None,
    }
}
fn select_cast_kind(
    types: &TypeArena,
    from: TypeId,
    to: TypeId,
    target: TargetProperties,
) -> Option<CastKind> {
    if from == to {
        return Some(CastKind::Identity);
    }
    Some(match (types.get(from), types.get(to)) {
        (Some(TypeData::Integer(a)), Some(TypeData::Integer(b)))
            if a.is_signed() != b.is_signed() =>
        {
            CastKind::IntegerSignednessChecked
        }
        (Some(TypeData::Integer(a)), Some(TypeData::Integer(b))) => {
            match a.bits(target).cmp(&b.bits(target)) {
                std::cmp::Ordering::Less if a.is_signed() => CastKind::IntegerExtendSigned,
                std::cmp::Ordering::Less => CastKind::IntegerExtendUnsigned,
                std::cmp::Ordering::Equal => CastKind::IntegerReencode,
                std::cmp::Ordering::Greater => CastKind::IntegerNarrowChecked,
            }
        }
        (Some(TypeData::Integer(a)), Some(TypeData::Float(_))) if a.is_signed() => {
            CastKind::SignedIntegerToFloat
        }
        (Some(TypeData::Integer(_)), Some(TypeData::Float(_))) => CastKind::UnsignedIntegerToFloat,
        (Some(TypeData::Float(_)), Some(TypeData::Integer(b))) if b.is_signed() => {
            CastKind::FloatToSignedIntegerChecked
        }
        (Some(TypeData::Float(_)), Some(TypeData::Integer(_))) => {
            CastKind::FloatToUnsignedIntegerChecked
        }
        _ if from == TypeId::FLOAT32 && to == TypeId::FLOAT64 => CastKind::FloatExtend,
        _ if from == TypeId::FLOAT64 && to == TypeId::FLOAT32 => CastKind::FloatTruncate,
        _ => return None,
    })
}

fn convert_constant(
    types: &TypeArena,
    value: ConstantValue,
    target: TypeId,
    properties: TargetProperties,
    span: Span,
) -> Result<ConstantValue, Vec<Diagnostic>> {
    match (value, types.get(target)) {
        (ConstantValue::Integer(value), Some(TypeData::Integer(integer))) => {
            let (min, max) = integer.range(properties);
            if value < min || value > max {
                return Err(vec![cast_range(value.to_string(), target, span)]);
            }
            Ok(ConstantValue::Integer(value))
        }
        (ConstantValue::Integer(value), _) if target == TypeId::FLOAT32 => Ok(
            ConstantValue::Float(FloatValue::Float32((value as f32).to_bits())),
        ),
        (ConstantValue::Integer(value), _) if target == TypeId::FLOAT64 => Ok(
            ConstantValue::Float(FloatValue::Float64((value as f64).to_bits())),
        ),
        (ConstantValue::Float(value), Some(TypeData::Integer(integer))) => {
            let number = float_as_f64(value);
            let (min, max) = integer.range(properties);
            let lower_ok = if integer.is_signed() {
                let min_float = integer_boundary_as_f64(value, min);
                let below = integer_boundary_as_f64(value, min - 1);
                if below == min_float {
                    number >= min_float
                } else {
                    number > below
                }
            } else {
                number > -1.0
            };
            let upper_exclusive = integer_boundary_as_f64(value, max + 1);
            if !number.is_finite() || !lower_ok || number >= upper_exclusive {
                return Err(vec![cast_range(format_float(value), target, span)]);
            }
            Ok(ConstantValue::Integer(number.trunc() as i128))
        }
        (ConstantValue::Float(value), _) if target == TypeId::FLOAT32 => Ok(ConstantValue::Float(
            FloatValue::Float32((float_as_f64(value) as f32).to_bits()),
        )),
        (ConstantValue::Float(value), _) if target == TypeId::FLOAT64 => Ok(ConstantValue::Float(
            FloatValue::Float64(float_as_f64(value).to_bits()),
        )),
        _ => unreachable!("bool conversions are rejected before constant conversion"),
    }
}

fn float_as_f64(value: FloatValue) -> f64 {
    match value {
        FloatValue::Float32(bits) => f64::from(f32::from_bits(bits)),
        FloatValue::Float64(bits) => f64::from_bits(bits),
    }
}

fn integer_boundary_as_f64(source: FloatValue, value: i128) -> f64 {
    match source {
        FloatValue::Float32(_) => f64::from(value as f32),
        FloatValue::Float64(_) => value as f64,
    }
}

fn format_float(value: FloatValue) -> String {
    match value {
        FloatValue::Float32(bits) => f32::from_bits(bits).to_string(),
        FloatValue::Float64(bits) => f64::from_bits(bits).to_string(),
    }
}

fn cast_range(value: impl std::fmt::Display, target: TypeId, span: Span) -> Diagnostic {
    Diagnostic::new(
        "E0231",
        Phase::Semantic,
        DiagnosticCategory::Conversion,
        format!("constant value `{value}` is outside the representable range of {target}"),
        Some(span),
    )
}

fn bin_result(
    types: &TypeArena,
    aop: AstBinaryOp,
    l: Checked,
    r: Checked,
    ty: TypeId,
    constant: Option<ConstantValue>,
) -> Checked {
    let float = types.float_info(l.expr.ty).is_some();
    let op = match aop {
        AstBinaryOp::Add if float => HirBinaryOp::AddFloat,
        AstBinaryOp::Subtract if float => HirBinaryOp::SubtractFloat,
        AstBinaryOp::Multiply if float => HirBinaryOp::MultiplyFloat,
        AstBinaryOp::Divide if float => HirBinaryOp::DivideFloat,
        AstBinaryOp::Add => HirBinaryOp::AddIntegerChecked,
        AstBinaryOp::Subtract => HirBinaryOp::SubtractIntegerChecked,
        AstBinaryOp::Multiply => HirBinaryOp::MultiplyIntegerChecked,
        AstBinaryOp::Divide => {
            if types.integer_info(l.expr.ty).unwrap().is_signed() {
                HirBinaryOp::DivideIntegerSignedChecked
            } else {
                HirBinaryOp::DivideIntegerUnsignedChecked
            }
        }
        AstBinaryOp::Remainder => {
            if types.integer_info(l.expr.ty).unwrap().is_signed() {
                HirBinaryOp::RemainderIntegerSignedChecked
            } else {
                HirBinaryOp::RemainderIntegerUnsignedChecked
            }
        }
        AstBinaryOp::Less => HirBinaryOp::Less,
        AstBinaryOp::LessEqual => HirBinaryOp::LessEqual,
        AstBinaryOp::Greater => HirBinaryOp::Greater,
        AstBinaryOp::GreaterEqual => HirBinaryOp::GreaterEqual,
        AstBinaryOp::Equal => HirBinaryOp::Equal,
        AstBinaryOp::NotEqual => HirBinaryOp::NotEqual,
        AstBinaryOp::LogicalAnd | AstBinaryOp::LogicalOr => {
            unreachable!("logical operators use dedicated short-circuit HIR")
        }
    };
    let span = l.expr.span.through(r.expr.span);
    Checked {
        expr: HirExpr {
            kind: HirExprKind::Binary {
                op,
                left: Box::new(l.expr),
                right: Box::new(r.expr),
            },
            ty,
            span,
        },
        constant,
    }
}
fn const_bin(
    op: AstBinaryOp,
    a: Option<ConstantValue>,
    b: Option<ConstantValue>,
    ty: IntegerType,
    span: Span,
    target: TargetProperties,
) -> Result<Option<ConstantValue>, Vec<Diagnostic>> {
    let (Some(ConstantValue::Integer(a)), Some(ConstantValue::Integer(b))) = (a, b) else {
        return Ok(None);
    };
    let value = match op {
        AstBinaryOp::Add => a.checked_add(b),
        AstBinaryOp::Subtract => a.checked_sub(b),
        AstBinaryOp::Multiply => a.checked_mul(b),
        AstBinaryOp::Divide | AstBinaryOp::Remainder if b == 0 => {
            return Err(vec![Diagnostic::new(
                "E0233",
                Phase::Semantic,
                DiagnosticCategory::Division,
                "constant integer division or remainder by zero",
                Some(span),
            )]);
        }
        AstBinaryOp::Divide if ty.is_signed() && a == ty.range(target).0 && b == -1 => {
            return Err(vec![Diagnostic::new(
                "E0234",
                Phase::Semantic,
                DiagnosticCategory::Division,
                format!("constant signed division overflows {ty}: MIN / -1"),
                Some(span),
            )]);
        }
        AstBinaryOp::Divide => a.checked_div(b),
        AstBinaryOp::Remainder if ty.is_signed() && a == ty.range(target).0 && b == -1 => Some(0),
        AstBinaryOp::Remainder => a.checked_rem(b),
        _ => return Ok(None),
    };
    Ok(value.map(ConstantValue::Integer))
}
fn builtin(n: &str) -> Option<TypeId> {
    Some(match n {
        "bool" => TypeId::BOOL,
        "int8" => TypeId::INT8,
        "int16" => TypeId::INT16,
        "int32" => TypeId::INT32,
        "int64" | "int" => TypeId::INT64,
        "uint8" | "byte" => TypeId::UINT8,
        "uint16" => TypeId::UINT16,
        "uint32" => TypeId::UINT32,
        "uint64" => TypeId::UINT64,
        "isize" => TypeId::ISIZE,
        "usize" => TypeId::USIZE,
        "float32" | "float" => TypeId::FLOAT32,
        "float64" | "double" => TypeId::FLOAT64,
        "string" => TypeId::STRING,
        "void" => TypeId::VOID,
        "char" => TypeId::CHAR,
        _ => return None,
    })
}
fn unknown_type(t: &AstType) -> Diagnostic {
    let name = t.named().map_or("<structural>", |(_, name, _)| name);
    Diagnostic::new(
        "E0204",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!("unknown type `{name}`"),
        Some(t.span),
    )
}
fn duplicate(k: &str, n: &str, s: Span) -> Diagnostic {
    Diagnostic::new(
        "E0203",
        Phase::Semantic,
        DiagnosticCategory::Name,
        format!("{k} `{n}` is already declared"),
        Some(s),
    )
}
fn unknown_name(n: &str, s: Span) -> Diagnostic {
    Diagnostic::new(
        "E0202",
        Phase::Semantic,
        DiagnosticCategory::Name,
        format!("unknown identifier `{n}`"),
        Some(s),
    )
}
fn type_error(m: impl Into<String>, s: Span) -> Diagnostic {
    Diagnostic::new(
        "E0205",
        Phase::Semantic,
        DiagnosticCategory::Type,
        m,
        Some(s),
    )
}

fn collection_admission_message(
    collection: &str,
    element: impl std::fmt::Display,
    admission: CollectionElementAdmission,
) -> String {
    match admission {
        CollectionElementAdmission::MissingStorable => format!(
            "{collection} element type `{element}` does not satisfy `Storable`: persistent storage legality cannot be proven; stored references and views require lifetime support not yet available"
        ),
        CollectionElementAdmission::MissingRelocatable => format!(
            "{collection} element type `{element}` does not satisfy `Relocatable`, required to relocate initialized elements during List growth"
        ),
        CollectionElementAdmission::InvalidType => {
            format!("{collection} element type {element} is invalid")
        }
        CollectionElementAdmission::Admitted => {
            format!("{collection} element type {element} is admitted")
        }
    }
}
fn conversion_error(
    types: &TypeArena,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    a: TypeId,
    b: TypeId,
    s: Span,
) -> Diagnostic {
    let detail = match (types.get(a), types.get(b)) {
        (Some(TypeData::Integer(x)), Some(TypeData::Integer(y)))
            if x.is_signed() != y.is_signed() =>
        {
            "mixed signed/unsigned operation"
        }
        (Some(TypeData::Integer(_)), Some(TypeData::Integer(_)))
        | (Some(TypeData::Float(_)), Some(TypeData::Float(_))) => "unsupported narrowing",
        _ if a == TypeId::BOOL || b == TypeId::BOOL => "bool has no numeric conversions",
        _ => "integer/float conversion is not implicit",
    };
    let code = if matches!(a, TypeId::BOOL) || matches!(b, TypeId::BOOL) {
        "E0205"
    } else {
        "E0218"
    };
    Diagnostic::new(
        code,
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!(
            "invalid implicit conversion from {} to {}: {detail}",
            format_type(types, a, structs, enums),
            format_type(types, b, structs, enums)
        ),
        Some(s),
    )
}
fn range(types: &TypeArena, text: &str, ty: TypeId, s: Span, t: TargetProperties) -> Diagnostic {
    let (min, max) = types
        .integer_info(ty)
        .unwrap_or(IntegerType::Int64)
        .range(t);
    Diagnostic::new(
        "E0209",
        Phase::Semantic,
        DiagnosticCategory::Integer,
        format!("integer literal `{text}` is outside {ty} range [{min}, {max}]"),
        Some(s),
    )
}
fn check_value(
    types: &TypeArena,
    v: i128,
    ty: TypeId,
    s: Span,
    t: TargetProperties,
) -> Result<(), Vec<Diagnostic>> {
    let (min, max) = types.integer_info(ty).unwrap().range(t);
    if v < min || v > max {
        Err(vec![Diagnostic::new(
            "E0210",
            Phase::Semantic,
            DiagnosticCategory::Integer,
            format!("constant integer expression overflows {ty}"),
            Some(s),
        )])
    } else {
        Ok(())
    }
}
fn validate_program(p: &ParsedProgram) -> Result<(), Vec<Diagnostic>> {
    let fail = |m| {
        vec![Diagnostic::new(
            "E0220",
            Phase::Semantic,
            DiagnosticCategory::Name,
            m,
            None,
        )]
    };
    if p.modules.is_empty() || p.entry.0 as usize >= p.modules.len() {
        return Err(fail("module graph has no valid entry module"));
    }
    let mut keys = BTreeSet::new();
    let mut sources = BTreeSet::new();
    let mut anonymous_source = None::<&str>;
    for (i, m) in p.modules.iter().enumerate() {
        if m.info.id.0 as usize != i || !keys.insert(&m.info.key) || !sources.insert(m.info.source)
        {
            return Err(fail("duplicate or non-canonical module/source identity"));
        }
        match &m.info.key.package {
            PackageKey::Named { path, .. } if !path.is_valid() => {
                return Err(fail("named package identity contains an empty PackagePath"));
            }
            PackageKey::Named { path, .. }
                if m.ast.package().is_none_or(|package| package.path != path.0) =>
            {
                return Err(fail(
                    "named package identity does not match its source declaration",
                ));
            }
            PackageKey::Anonymous if m.ast.package().is_some() => {
                return Err(fail(
                    "anonymous package identity has a named source declaration",
                ));
            }
            PackageKey::Anonymous => {
                if let Some(first) = anonymous_source.replace(&m.info.source_name) {
                    return Err(vec![Diagnostic::new(
                        "E0241",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "V1 permits only one source unit without a package declaration per source graph; first `{first}`, second `{}`",
                            m.info.source_name
                        ),
                        None,
                    )
                    .with_source_name(&m.info.source_name)]);
                }
            }
            PackageKey::Named { .. } => {}
        }
        let mut imports = BTreeSet::new();
        for x in &m.info.imports {
            let valid_target =
                x.target
                    .named_parts()
                    .is_some_and(|(target_origin, target_path)| {
                        p.modules
                            .get(x.module.0 as usize)
                            .is_some_and(|target_module| {
                                target_module.info.key.package.named_parts().is_some_and(
                                    |(module_origin, module_path)| {
                                        module_origin == target_origin
                                            && module_path.starts_with(target_path)
                                    },
                                )
                            })
                    });
            if !valid_target || !imports.insert((&x.target, &x.alias)) {
                let detail = if matches!(x.target, PackageKey::Anonymous) {
                    "anonymous package is not importable"
                } else {
                    "duplicate or invalid import"
                };
                return Err(vec![
                    Diagnostic::new(
                        "E0220",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("{detail} `{}`", x.name),
                        Some(x.span),
                    )
                    .with_source_name(&m.info.source_name),
                ]);
            }
        }
    }
    Ok(())
}

pub fn verify_hir(h: &TypedHir) -> Result<(), Vec<Diagnostic>> {
    verify_parametric_hir(
        &h.generic_functions,
        &h.signatures,
        &h.structs,
        &h.enums,
        &h.types,
    )?;
    let fail = |m: String| {
        vec![Diagnostic::new(
            "E0290",
            Phase::Semantic,
            DiagnosticCategory::Verification,
            m,
            None,
        )]
    };
    if h.modules.is_empty()
        || h.entry.0 as usize >= h.instances.len()
        || h.functions.len() != h.instances.len()
    {
        return Err(fail("HIR cardinality invalid".into()));
    }
    if h.types.entries().any(|(_, data)| match data {
        TypeData::Buffer { element } | TypeData::View { element, .. } => {
            !h.types.is_admitted_buffer_element(*element)
        }
        TypeData::Matrix { element } => !h.types.is_admitted_matrix_element(*element),
        TypeData::Vector { element, .. } => !h.types.is_admitted_vector_element(*element),
        TypeData::Array { element } => !h.types.is_admitted_array_element(*element),
        TypeData::List { element } => !h.types.is_admitted_list_element(*element),
        _ => false,
    }) {
        return Err(fail(
            "HIR contains a Buffer/View/Array/List/Vector with an inadmissible element type".into(),
        ));
    }
    for ty in h
        .instances
        .iter()
        .flat_map(|signature| {
            signature
                .parameters
                .iter()
                .map(|p| p.ty)
                .chain(std::iter::once(signature.return_type))
        })
        .chain(
            h.structs
                .iter()
                .flat_map(|info| info.fields.iter().map(|field| field.ty)),
        )
        .chain(h.enums.iter().flat_map(|info| {
            info.variants
                .iter()
                .flat_map(|variant| variant.payloads.iter().map(|payload| payload.ty))
        }))
        .chain(h.functions.iter().flat_map(|function| {
            function
                .locals
                .iter()
                .map(|local| local.ty)
                .chain(function.parameters.iter().map(|parameter| parameter.ty))
        }))
    {
        if !h.types.is_valid(ty) {
            return Err(fail(format!("HIR references invalid TypeId({})", ty.0)));
        }
        if !hir_value_type_is_complete(&h.types, ty, &h.structs, &h.enums) {
            return Err(fail(format!(
                "HIR value type {} is an incomplete generic application",
                format_type(&h.types, ty, &h.structs, &h.enums)
            )));
        }
    }
    let e = &h.instances[h.entry.0 as usize];
    if e.name != "main" || e.return_type != TypeId::INT64 || !e.parameters.is_empty() {
        return Err(fail("HIR entry invalid".into()));
    }
    if h.instances.iter().any(|signature| {
        h.types.contains_reference(signature.return_type)
            || h.types.contains_view(signature.return_type)
    }) || h.structs.iter().any(|info| {
        info.fields
            .iter()
            .any(|field| h.types.contains_reference(field.ty) || h.types.contains_view(field.ty))
    }) || h.enums.iter().any(|info| {
        info.variants.iter().any(|variant| {
            variant.payloads.iter().any(|payload| {
                h.types.contains_reference(payload.ty) || h.types.contains_view(payload.ty)
            })
        })
    }) {
        return Err(fail(
            "HIR violates borrowed-value non-escape storage rules".into(),
        ));
    }
    let mut next_field = 0_u32;
    for (index, info) in h.structs.iter().enumerate() {
        if info.id.0 as usize != index || info.layout.align == 0 {
            return Err(fail("HIR struct identity/layout invalid".into()));
        }
        for (field_index, field) in info.fields.iter().enumerate() {
            if field.id.0 != next_field
                || field.owner != info.id
                || field.index as usize != field_index
            {
                return Err(fail("HIR field identity invalid".into()));
            }
            next_field += 1;
        }
    }
    for (index, info) in h.enums.iter().enumerate() {
        if info.id.0 as usize != index || info.layout.align == 0 || info.variants.is_empty() {
            return Err(fail("HIR enum identity/layout invalid".into()));
        }
        for (variant_index, variant) in info.variants.iter().enumerate() {
            if variant.id
                != (VariantId {
                    enum_id: info.id,
                    index: variant_index as u32,
                })
                || variant.owner != info.id
                || variant.index as usize != variant_index
                || variant.discriminant != variant.index
            {
                return Err(fail("HIR variant identity invalid".into()));
            }
            for (payload_index, payload) in variant.payloads.iter().enumerate() {
                if payload.index as usize != payload_index {
                    return Err(fail("HIR variant payload identity invalid".into()));
                }
            }
        }
    }
    for (i, (s, f)) in h.instances.iter().zip(&h.functions).enumerate() {
        if s.id.0 as usize != i
            || f.id != s.id
            || f.function_id != s.function_id
            || f.module != s.module
        {
            return Err(fail("HIR function identity mismatch".into()));
        }
        for (j, l) in f.locals.iter().enumerate() {
            if l.id.0 as usize != j {
                return Err(fail("HIR local identity invalid".into()));
            }
        }
        for (parameter, signature) in f.parameters.iter().zip(&s.parameters) {
            let Some(local) = f.locals.get(parameter.local.0 as usize) else {
                return Err(fail("HIR parameter binding is missing".into()));
            };
            if !local.parameter
                || !local.source_binding
                || local.mutability != parameter.mutability
                || parameter.mutability != signature.mutability
            {
                return Err(fail("HIR parameter binding mutability is invalid".into()));
            }
        }
        crate::verify_class_signature(
            &h.types,
            s.function_id,
            s.module,
            &s.parameters.iter().map(|p| p.ty).collect::<Vec<_>>(),
            s.return_type,
        )
        .map_err(&fail)?;
        verify_hir_const_initializers(&f.body, &f.locals, &f.parameters, &fail)?;
        classes::verify_body(
            &f.body,
            &f.locals,
            &f.parameters,
            f.function_id,
            s.module,
            &h.types,
            VerificationSignatures::Concrete(&h.instances),
        )
        .map_err(&fail)?;
        classes::verify_constructor_unwind_plan(
            f.constructor_unwind.as_ref(),
            &f.locals,
            &f.parameters,
            f.function_id,
            &h.types,
        )
        .map_err(&fail)?;
        verify_finally_identities(&f.body, &fail)?;
        verify_block(
            &f.body,
            &VerificationFunction { locals: &f.locals },
            s.return_type,
            VerificationSignatures::Concrete(&h.instances),
            &h.structs,
            &h.enums,
            &h.types,
            &[],
            &fail,
        )?
    }
    Ok(())
}

fn hir_value_type_is_complete(
    types: &TypeArena,
    ty: TypeId,
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> bool {
    match types.get(ty) {
        Some(TypeData::Struct(id)) => structs
            .get(id.0 as usize)
            .is_some_and(|info| info.generic_parameters.is_empty()),
        Some(TypeData::Enum(id)) => enums
            .get(id.0 as usize)
            .is_some_and(|info| info.generic_parameters.is_empty()),
        Some(TypeData::StructInstance(id, arguments)) => structs
            .get(id.0 as usize)
            .zip(types.arguments(*arguments))
            .is_some_and(|(info, arguments)| {
                !info.generic_parameters.is_empty()
                    && info.generic_parameters.len() == arguments.len()
                    && arguments.iter().all(|argument| {
                        hir_value_type_is_complete(types, *argument, structs, enums)
                    })
            }),
        Some(TypeData::EnumInstance(id, arguments)) => enums
            .get(id.0 as usize)
            .zip(types.arguments(*arguments))
            .is_some_and(|(info, arguments)| {
                !info.generic_parameters.is_empty()
                    && info.generic_parameters.len() == arguments.len()
                    && arguments.iter().all(|argument| {
                        hir_value_type_is_complete(types, *argument, structs, enums)
                    })
            }),
        Some(
            TypeData::Nullable(payload)
            | TypeData::Reference {
                pointee: payload, ..
            },
        ) => hir_value_type_is_complete(types, *payload, structs, enums),
        Some(TypeData::Function { parameters, result }) => {
            types.arguments(*parameters).is_some_and(|parameters| {
                parameters
                    .iter()
                    .all(|parameter| hir_value_type_is_complete(types, *parameter, structs, enums))
            }) && hir_value_type_is_complete(types, *result, structs, enums)
        }
        Some(
            TypeData::Buffer { element }
            | TypeData::Array { element }
            | TypeData::Matrix { element }
            | TypeData::Vector { element, .. }
            | TypeData::List { element }
            | TypeData::View { element, .. }
            | TypeData::VectorView { element, .. }
            | TypeData::MatrixView { element, .. },
        ) => hir_value_type_is_complete(types, *element, structs, enums),
        Some(_) => true,
        None => false,
    }
}
/// Shared borrowed body context; generic verification creates no `InstanceId`.
struct VerificationFunction<'a> {
    locals: &'a [HirLocal],
}

#[derive(Clone, Copy)]
enum VerificationSignatures<'a> {
    Concrete(&'a [FunctionInstanceInfo]),
    Parametric(&'a [FunctionSignature]),
}

fn verify_parametric_hir(
    declarations: &[GenericHirFunction],
    signatures: &[FunctionSignature],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
) -> Result<(), Vec<Diagnostic>> {
    let fail = |message: String| {
        vec![Diagnostic::new(
            "E0348",
            Phase::Semantic,
            DiagnosticCategory::Verification,
            message,
            None,
        )]
    };
    crate::verify_class_metadata(types, structs, enums).map_err(&fail)?;
    for parameter in signatures
        .iter()
        .flat_map(|s| &s.generic_parameters)
        .chain(structs.iter().flat_map(|s| &s.generic_parameters))
        .chain(enums.iter().flat_map(|s| &s.generic_parameters))
    {
        if types.generic_param(parameter.ty) != Some(parameter.id)
            || types.generic_capabilities(parameter.id) != Some(&parameter.capabilities)
            || types.generic_name(parameter.id) != Some(parameter.name.as_str())
        {
            return Err(fail(
                "HIR generic capability declaration/arena metadata mismatch".into(),
            ));
        }
    }
    if declarations.len() != signatures.len() {
        return Err(fail(
            "HIR parametric declaration cardinality invalid".into(),
        ));
    }
    for (index, (declaration, signature)) in declarations.iter().zip(signatures).enumerate() {
        if declaration.id != signature.id || declaration.id.0 as usize != index {
            return Err(fail("HIR parametric declaration identity invalid".into()));
        }
        crate::verify_class_signature(
            types,
            signature.id,
            signature.module,
            &signature
                .parameters
                .iter()
                .map(|p| p.ty)
                .collect::<Vec<_>>(),
            signature.return_type,
        )
        .map_err(&fail)?;
        let function = VerificationFunction {
            locals: &declaration.locals,
        };
        for (parameter, signature_parameter) in
            declaration.parameters.iter().zip(&signature.parameters)
        {
            let Some(local) = declaration.locals.get(parameter.local.0 as usize) else {
                return Err(fail("generic HIR parameter binding is missing".into()));
            };
            if !local.parameter
                || !local.source_binding
                || local.mutability != parameter.mutability
                || parameter.mutability != signature_parameter.mutability
            {
                return Err(fail(
                    "generic HIR parameter binding mutability is invalid".into(),
                ));
            }
        }
        verify_hir_const_initializers(
            &declaration.body,
            &declaration.locals,
            &declaration.parameters,
            &fail,
        )?;
        classes::verify_body(
            &declaration.body,
            &declaration.locals,
            &declaration.parameters,
            declaration.id,
            signature.module,
            types,
            VerificationSignatures::Parametric(signatures),
        )
        .map_err(&fail)?;
        classes::verify_constructor_unwind_plan(
            declaration.constructor_unwind.as_ref(),
            &declaration.locals,
            &declaration.parameters,
            declaration.id,
            types,
        )
        .map_err(&fail)?;
        verify_finally_identities(&declaration.body, &fail)?;
        verify_block(
            &declaration.body,
            &function,
            signature.return_type,
            VerificationSignatures::Parametric(signatures),
            structs,
            enums,
            types,
            &[],
            &fail,
        )?;
    }
    Ok(())
}

fn verify_hir_const_initializers(
    body: &HirBlock,
    locals: &[HirLocal],
    parameters: &[HirParameter],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    fn visit(block: &HirBlock, counts: &mut [u32]) -> bool {
        for statement in &block.statements {
            match &statement.kind {
                HirStmtKind::Local { local, .. } => {
                    let Some(count) = counts.get_mut(local.0 as usize) else {
                        return false;
                    };
                    *count += 1;
                }
                HirStmtKind::If {
                    then_block,
                    else_block,
                    ..
                } => {
                    if !visit(then_block, counts) {
                        return false;
                    }
                    if let Some(block) = else_block {
                        if !visit(block, counts) {
                            return false;
                        }
                    }
                }
                HirStmtKind::While { body, .. }
                | HirStmtKind::ForRange { body, .. }
                | HirStmtKind::ForCollection { body, .. } => {
                    if !visit(body, counts) {
                        return false;
                    }
                }
                HirStmtKind::Match { arms, .. } => {
                    for arm in arms {
                        if !visit(&arm.body, counts) {
                            return false;
                        }
                    }
                }
                HirStmtKind::Try {
                    body,
                    catches,
                    finally,
                } => {
                    if !visit(body, counts) {
                        return false;
                    }
                    for catch in catches {
                        if !visit(&catch.body, counts) {
                            return false;
                        }
                    }
                    if let Some(finally) = finally {
                        if !visit(&finally.body, counts) {
                            return false;
                        }
                    }
                }
                _ => {}
            }
        }
        true
    }

    let parameter_ids = parameters
        .iter()
        .map(|parameter| parameter.local)
        .collect::<BTreeSet<_>>();
    let mut counts = vec![0_u32; locals.len()];
    if !visit(body, &mut counts) {
        return Err(fail("HIR const initializer names an invalid local".into()));
    }
    for local in locals {
        if !local.source_binding && local.mutability == crate::BindingMutability::Const {
            return Err(fail("compiler-owned HIR local is marked const".into()));
        }
        if local.source_binding && local.mutability == crate::BindingMutability::Const {
            let expected = u32::from(!parameter_ids.contains(&local.id));
            if counts[local.id.0 as usize] != expected {
                return Err(fail(
                    "HIR const binding does not have exactly one initializer".into(),
                ));
            }
        }
    }
    Ok(())
}

fn verify_block(
    b: &HirBlock,
    f: &VerificationFunction<'_>,
    ret: TypeId,
    sigs: VerificationSignatures<'_>,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    active_catches: &[CatchId],
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut seen_exit_drops = BTreeSet::new();
    for drop in &b.exit_drops {
        let local = drop.local();
        if !seen_exit_drops.insert(local)
            || !f
                .locals
                .get(local.0 as usize)
                .is_some_and(|info| !types.guarantees_copy(info.ty) && types.needs_drop(info.ty))
        {
            return Err(fail("HIR block cleanup contract is invalid".into()));
        }
    }
    for s in &b.statements {
        match &s.kind {
            HirStmtKind::Nop => {}
            HirStmtKind::Local { local, initializer } => {
                verify_expr(initializer, f, sigs, structs, enums, types, fail)?;
                if f.locals.get(local.0 as usize).map(|l| l.ty) != Some(initializer.ty) {
                    return Err(fail("HIR assignment mismatch".into()));
                }
            }
            HirStmtKind::Assign { place, value } => {
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                verify_place(place, f, sigs, structs, enums, types, fail)?;
                if place.ty != value.ty {
                    return Err(fail("HIR field assignment mismatch".into()));
                }
                if !hir_place_writable(place, f, types, structs, enums) {
                    return Err(fail("HIR writes through a shared reference".into()));
                }
                if hir_const_inline_root(place, f).is_some() {
                    return Err(fail("HIR writes const inline storage".into()));
                }
                if !types.guarantees_copy(place.ty)
                    && place.ty != TypeId::STRING
                    && (!place.projections.is_empty()
                        || matches!(place.base, HirPlaceBase::Dereference { .. }))
                {
                    return Err(fail(
                        "HIR partial replacement of a non-Copy value is invalid".into(),
                    ));
                }
            }
            HirStmtKind::StringOutput {
                function,
                value,
                newline,
            } => {
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                let call = crate::CoreCall {
                    function: function.clone(),
                    arguments: vec![value.clone()],
                };
                if !matches!(
                    function.symbol,
                    crate::CoreSymbol::Print | crate::CoreSymbol::Println
                ) || *newline != (function.symbol == crate::CoreSymbol::Println)
                    || crate::verify_core_call(&call, TypeId::BOOL, types, |operand| Ok(operand.ty))
                        .is_err()
                {
                    return Err(fail("HIR string output operand is not string".into()));
                }
            }
            HirStmtKind::ListPush {
                target,
                value,
                mutation,
            } => {
                verify_place(target, f, sigs, structs, enums, types, fail)?;
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                if *mutation != StructuralMutation::Push
                    || types.list_element(target.ty) != Some(value.ty)
                    || matches!(
                        target.base,
                        HirPlaceBase::Dereference { mutable: false, .. }
                    )
                {
                    return Err(fail("HIR List push contract invalid".into()));
                }
            }
            HirStmtKind::ListReserve {
                target,
                requested_capacity,
                mutation,
            } => {
                verify_place(target, f, sigs, structs, enums, types, fail)?;
                verify_expr(requested_capacity, f, sigs, structs, enums, types, fail)?;
                if *mutation != StructuralMutation::Reserve
                    || types.list_element(target.ty).is_none()
                    || requested_capacity.ty != TypeId::USIZE
                    || matches!(
                        target.base,
                        HirPlaceBase::Dereference { mutable: false, .. }
                    )
                {
                    return Err(fail("HIR List reserve contract invalid".into()));
                }
            }
            HirStmtKind::If {
                condition,
                then_block,
                else_block,
            } => {
                verify_expr(condition, f, sigs, structs, enums, types, fail)?;
                if condition.ty != TypeId::BOOL {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(
                    then_block,
                    f,
                    ret,
                    sigs,
                    structs,
                    enums,
                    types,
                    active_catches,
                    fail,
                )?;
                if let Some(x) = else_block {
                    verify_block(x, f, ret, sigs, structs, enums, types, active_catches, fail)?
                }
            }
            HirStmtKind::While { condition, body } => {
                verify_expr(condition, f, sigs, structs, enums, types, fail)?;
                if condition.ty != TypeId::BOOL {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(
                    body,
                    f,
                    ret,
                    sigs,
                    structs,
                    enums,
                    types,
                    active_catches,
                    fail,
                )?
            }
            HirStmtKind::ForRange {
                binding,
                item_type,
                start,
                step,
                end,
                step_is_implicit,
                body,
                ..
            } => {
                verify_expr(start, f, sigs, structs, enums, types, fail)?;
                verify_expr(step, f, sigs, structs, enums, types, fail)?;
                verify_expr(end, f, sigs, structs, enums, types, fail)?;
                if *item_type != TypeId::INT64
                    || start.ty != *item_type
                    || step.ty != *item_type
                    || end.ty != *item_type
                    || f.locals.get(binding.0 as usize).map(|local| local.ty) != Some(*item_type)
                    || (*step_is_implicit && !matches!(step.kind, HirExprKind::Int(1)))
                    || matches!(step.kind, HirExprKind::Int(0))
                {
                    return Err(fail("HIR int range protocol is invalid".into()));
                }
                verify_block(
                    body,
                    f,
                    ret,
                    sigs,
                    structs,
                    enums,
                    types,
                    active_catches,
                    fail,
                )?;
            }
            HirStmtKind::ForCollection {
                binding,
                iterable_type,
                item_type,
                binding_type,
                category,
                source,
                structural_borrow,
                body,
                ..
            } => {
                let source_type = match source {
                    CollectionIterationSource::Borrowed(place) => {
                        verify_place(place, f, sigs, structs, enums, types, fail)?;
                        place.ty
                    }
                    CollectionIterationSource::Temporary { root, initializer } => {
                        verify_expr(initializer, f, sigs, structs, enums, types, fail)?;
                        if f.locals.get(root.0 as usize).is_none_or(|local| {
                            local.ty != initializer.ty || local.parameter || !local.address_taken
                        }) {
                            return Err(fail(
                                "HIR collection temporary root contract is invalid".into(),
                            ));
                        }
                        initializer.ty
                    }
                };
                let actual_item = types
                    .array_element(*iterable_type)
                    .or_else(|| types.list_element(*iterable_type));
                let is_list = types.list_element(*iterable_type).is_some();
                let valid_binding = match category {
                    IterationBindingCategory::CopyValue => {
                        *binding_type == *item_type && types.guarantees_copy(*item_type)
                    }
                    IterationBindingCategory::SharedElementBorrow => {
                        !types.guarantees_copy(*item_type)
                            && types.reference_info(*binding_type) == Some((*item_type, false))
                    }
                };
                if source_type != *iterable_type
                    || actual_item != Some(*item_type)
                    || !valid_binding
                    || *structural_borrow != is_list
                    || f.locals.get(binding.0 as usize).map(|local| local.ty) != Some(*binding_type)
                {
                    return Err(fail("HIR collection iteration protocol is invalid".into()));
                }
                verify_block(
                    body,
                    f,
                    ret,
                    sigs,
                    structs,
                    enums,
                    types,
                    active_catches,
                    fail,
                )?;
            }
            HirStmtKind::Match {
                mode,
                scrutinee,
                enum_type,
                enum_id,
                arms,
            } => {
                verify_expr(scrutinee, f, sigs, structs, enums, types, fail)?;
                let Some(info) = enums
                    .get(enum_id.0 as usize)
                    .filter(|info| info.id == *enum_id)
                else {
                    return Err(fail("HIR match has unknown enum".into()));
                };
                let valid_scrutinee = match mode {
                    MatchMode::Value => scrutinee.ty == *enum_type,
                    MatchMode::SharedRef => {
                        types.reference_info(scrutinee.ty) == Some((*enum_type, false))
                            && matches!(scrutinee.kind, HirExprKind::Borrow { mutable: false, .. })
                    }
                    MatchMode::MutableRef => {
                        types.reference_info(scrutinee.ty) == Some((*enum_type, true))
                            && matches!(scrutinee.kind, HirExprKind::Borrow { mutable: true, .. })
                    }
                };
                if types.enum_id(*enum_type) != Some(*enum_id)
                    || !valid_scrutinee
                    || arms.len() != info.variants.len()
                {
                    return Err(fail("HIR match type/exhaustiveness invalid".into()));
                }
                if *mode == MatchMode::Value
                    && !types.guarantees_copy(*enum_type)
                    && matches!(scrutinee.kind, HirExprKind::Local(_) | HirExprKind::Load(_))
                {
                    return Err(fail(
                        "HIR non-Copy value match does not consume its enum root".into(),
                    ));
                }
                let mut seen = BTreeSet::new();
                for arm in arms {
                    let Some(variant) = info
                        .variants
                        .get(arm.variant_id.index as usize)
                        .filter(|variant| variant.id == arm.variant_id)
                    else {
                        return Err(fail("HIR match variant does not belong to enum".into()));
                    };
                    if !seen.insert(arm.variant_id)
                        || (!arm.bindings.is_empty()
                            && arm.bindings.len() != variant.payloads.len())
                    {
                        return Err(fail(
                            "HIR match variant duplication/binding arity invalid".into(),
                        ));
                    }
                    for (binding, payload) in arm.bindings.iter().zip(&variant.payloads) {
                        let expected =
                            concrete_member_type(types, *enum_type, payload.ty, structs, enums)
                                .ok_or_else(|| fail("HIR match substitution incomplete".into()))?;
                        let expected = match mode {
                            MatchMode::Value => expected,
                            MatchMode::SharedRef => types
                                .id_of(TypeData::Reference {
                                    pointee: expected,
                                    mutable: false,
                                })
                                .ok_or_else(|| fail("HIR match shared-ref type missing".into()))?,
                            MatchMode::MutableRef => types
                                .id_of(TypeData::Reference {
                                    pointee: expected,
                                    mutable: true,
                                })
                                .ok_or_else(|| fail("HIR match mutable-ref type missing".into()))?,
                        };
                        if binding.payload_index != payload.index
                            || binding.ty != expected
                            || f.locals.get(binding.local.0 as usize).map(|local| local.ty)
                                != Some(expected)
                        {
                            return Err(fail("HIR match payload binding invalid".into()));
                        }
                    }
                    verify_block(
                        &arm.body,
                        f,
                        ret,
                        sigs,
                        structs,
                        enums,
                        types,
                        active_catches,
                        fail,
                    )?;
                }
            }
            HirStmtKind::Return { value, drops } => {
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                let mut seen = BTreeSet::new();
                if value.ty != ret
                    || drops.iter().any(|drop| {
                        let local = drop.local();
                        !seen.insert(local)
                            || !f.locals.get(local.0 as usize).is_some_and(|info| {
                                !types.guarantees_copy(info.ty) && types.needs_drop(info.ty)
                            })
                    })
                {
                    return Err(fail("HIR return mismatch".into()));
                }
            }
            HirStmtKind::Break { drops } | HirStmtKind::Continue { drops } => {
                let mut seen = BTreeSet::new();
                if drops.iter().any(|drop| {
                    let local = drop.local();
                    !seen.insert(local)
                        || !f.locals.get(local.0 as usize).is_some_and(|info| {
                            !types.guarantees_copy(info.ty) && types.needs_drop(info.ty)
                        })
                }) {
                    return Err(fail("HIR loop transfer cleanup contract is invalid".into()));
                }
            }
            HirStmtKind::Throw {
                value,
                class,
                transfer,
                drops,
            } => {
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                let actual_transfer = matches!(
                    value.kind,
                    HirExprKind::Class(ref op)
                        if matches!(op.as_ref(), ClassOp::Construct { .. } | ClassOp::HandleTransfer { .. } | ClassOp::ClassUpcast { transfer: true, .. })
                );
                let mut seen = BTreeSet::new();
                if types.class_id(value.ty) != Some(*class)
                    || !types.is_exception_class(*class)
                    || actual_transfer != *transfer
                    || drops.iter().any(|drop| {
                        let local = drop.local();
                        !seen.insert(local)
                            || !f.locals.get(local.0 as usize).is_some_and(|info| {
                                !types.guarantees_copy(info.ty) && types.needs_drop(info.ty)
                            })
                    })
                {
                    return Err(fail("HIR throw ownership/type contract is invalid".into()));
                }
            }
            HirStmtKind::Rethrow { catch, drops } => {
                let mut seen = BTreeSet::new();
                if active_catches.last() != Some(catch)
                    || drops.iter().any(|drop| {
                        let local = drop.local();
                        !seen.insert(local)
                            || !f.locals.get(local.0 as usize).is_some_and(|info| {
                                !types.guarantees_copy(info.ty) && types.needs_drop(info.ty)
                            })
                    })
                {
                    return Err(fail("HIR rethrow cleanup contract is invalid".into()));
                }
            }
            HirStmtKind::Try {
                body,
                catches,
                finally,
            } => {
                verify_block(
                    body,
                    f,
                    ret,
                    sigs,
                    structs,
                    enums,
                    types,
                    active_catches,
                    fail,
                )?;
                if catches.is_empty() && finally.is_none() {
                    return Err(fail("HIR try has neither catches nor finally".into()));
                }
                let mut ids = BTreeSet::new();
                let mut previous = Vec::new();
                for catch in catches {
                    let binding_ty = f.locals.get(catch.binding.0 as usize).map(|local| local.ty);
                    if !ids.insert(catch.id)
                        || binding_ty.and_then(|ty| types.class_id(ty)) != Some(catch.class)
                        || !types.is_exception_class(catch.class)
                        || previous
                            .iter()
                            .any(|earlier| types.is_subclass(catch.class, *earlier))
                    {
                        return Err(fail("HIR catch identity/order contract is invalid".into()));
                    }
                    previous.push(catch.class);
                    let mut nested_catches = active_catches.to_vec();
                    nested_catches.push(catch.id);
                    verify_block(
                        &catch.body,
                        f,
                        ret,
                        sigs,
                        structs,
                        enums,
                        types,
                        &nested_catches,
                        fail,
                    )?;
                }
                if let Some(finally) = finally {
                    verify_block(
                        &finally.body,
                        f,
                        ret,
                        sigs,
                        structs,
                        enums,
                        types,
                        active_catches,
                        fail,
                    )?;
                    if block_may_throw_or_transfer(&finally.body) {
                        return Err(fail(
                            "HIR finally is not a non-throwing normal region".into(),
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}
fn verify_expr(
    e: &HirExpr,
    f: &VerificationFunction<'_>,
    sigs: VerificationSignatures<'_>,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    if !types.is_valid(e.ty) {
        return Err(fail(format!(
            "HIR expression references invalid TypeId({})",
            e.ty.0
        )));
    }
    match &e.kind {
        HirExprKind::Class(op) => {
            for operand in op.operands() {
                verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            }
            crate::verify_class_op(
                op,
                e.ty,
                types,
                |e| Ok(e.ty),
                |target| {
                    match (sigs, target) {
                        (
                            VerificationSignatures::Parametric(ss),
                            HirCallTarget::Declaration(id),
                        ) => ss.get(id.0 as usize).filter(|s| s.id == *id).map(|s| {
                            (
                                s.id,
                                s.parameters.iter().map(|p| p.ty).collect(),
                                s.return_type,
                            )
                        }),
                        (VerificationSignatures::Concrete(ss), HirCallTarget::Instance(id)) => {
                            ss.get(id.0 as usize).filter(|s| s.id == *id).map(|s| {
                                (
                                    s.function_id,
                                    s.parameters.iter().map(|p| p.ty).collect(),
                                    s.return_type,
                                )
                            })
                        }
                        _ => None,
                    }
                    .ok_or_else(|| "invalid class call target".into())
                },
            )
            .map_err(fail)?;
            if let ClassOp::HandleAlias { source } = op.as_ref()
                && !matches!(source.kind, HirExprKind::Local(_))
            {
                return Err(fail("HIR Alias requires a class lvalue".into()));
            }
            if let ClassOp::HandleTransfer { source } = op.as_ref()
                && matches!(source.kind, HirExprKind::Local(_) | HirExprKind::Load(_))
            {
                return Err(fail(
                    "HIR Transfer cannot consume an ordinary class lvalue".into(),
                ));
            }
        }
        HirExprKind::String(op) => {
            for operand in op.operands() {
                verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            }
            crate::verify_string_op(op, e.ty, types, |operand| Ok(operand.ty)).map_err(fail)?;
            if let crate::StringOp::Alias { source } = op.as_ref()
                && !matches!(source.kind, HirExprKind::Local(_) | HirExprKind::Load(_))
            {
                return Err(fail("HIR string Alias requires an lvalue".into()));
            }
        }
        HirExprKind::Text { call_site, op } => {
            for (index, operand) in op.operands().into_iter().enumerate() {
                if matches!(operand.kind, HirExprKind::CallScopedSharedBorrow { .. }) {
                    verify_call_borrow(
                        operand, *call_site, index, f, sigs, structs, enums, types, fail,
                    )?;
                } else {
                    verify_expr(operand, f, sigs, structs, enums, types, fail)?;
                }
            }
            crate::verify_text_op(op, e.ty, types, structs, enums, |operand| Ok(operand.ty))
                .map_err(fail)?;
        }
        HirExprKind::Core(op) => {
            for operand in op.operands() {
                verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            }
            crate::verify_core_call(op, e.ty, types, |operand| Ok(operand.ty)).map_err(fail)?;
        }
        HirExprKind::Int(_) if types.integer_info(e.ty).is_none() && e.ty != TypeId::CHAR => {
            return Err(fail("HIR integer literal mismatch".into()));
        }
        HirExprKind::Float(FloatValue::Float32(_)) if e.ty != TypeId::FLOAT32 => {
            return Err(fail("HIR float32 mismatch".into()));
        }
        HirExprKind::Float(FloatValue::Float64(_)) if e.ty != TypeId::FLOAT64 => {
            return Err(fail("HIR float64 mismatch".into()));
        }
        HirExprKind::Bool(_) if e.ty != TypeId::BOOL => {
            return Err(fail("HIR bool mismatch".into()));
        }
        HirExprKind::Local(l) | HirExprKind::Move(l)
            if f.locals.get(l.0 as usize).map(|x| x.ty) != Some(e.ty) =>
        {
            return Err(fail("HIR local mismatch".into()));
        }
        HirExprKind::Move(_) if types.guarantees_copy(e.ty) => {
            return Err(fail("HIR Move used for a Copy type".into()));
        }
        HirExprKind::Load(place) => {
            verify_place(place, f, sigs, structs, enums, types, fail)?;
            if place.ty != e.ty || (!types.guarantees_copy(e.ty) && e.ty != TypeId::STRING) {
                return Err(fail("HIR load/place type mismatch".into()));
            }
        }
        HirExprKind::Borrow { place, mutable } => {
            verify_place(place, f, sigs, structs, enums, types, fail)?;
            if types.reference_info(e.ty) != Some((place.ty, *mutable)) {
                return Err(fail("HIR borrow type/capability mismatch".into()));
            }
            if *mutable && hir_const_inline_root(place, f).is_some() {
                return Err(fail("HIR mutably borrows const inline storage".into()));
            }
            if *mutable && !hir_place_writable(place, f, types, structs, enums) {
                return Err(fail("HIR mutable borrow through shared reference".into()));
            }
            if let HirPlaceBase::Local(local) = &place.base
                && !place
                    .projections
                    .iter()
                    .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
                && !f.locals[local.0 as usize].address_taken
            {
                return Err(fail(
                    "HIR borrowed local is not marked address-taken".into(),
                ));
            }
        }
        HirExprKind::CallScopedSharedBorrow { .. } => {
            return Err(fail(
                "HIR call-scoped borrow appears outside its exact argument slot".into(),
            ));
        }
        HirExprKind::BufferInit {
            element_type,
            length,
            initial,
        } => {
            verify_expr(length, f, sigs, structs, enums, types, fail)?;
            verify_expr(initial, f, sigs, structs, enums, types, fail)?;
            if types.buffer_element(e.ty) != Some(*element_type)
                || length.ty != TypeId::USIZE
                || initial.ty != *element_type
                || !types.guarantees_copy(*element_type)
                || types.needs_drop(*element_type)
            {
                return Err(fail("HIR Buffer construction contract invalid".into()));
            }
        }
        HirExprKind::VectorTranspose {
            operand,
            source_type,
        } => {
            verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            if operand.ty != *source_type
                || matches!(operand.kind, HirExprKind::Local(_) | HirExprKind::Load(_))
                || !matches!((types.get(*source_type), types.get(e.ty)),
                (Some(TypeData::Vector { element: a, orientation: x }),
                 Some(TypeData::Vector { element: b, orientation: y }))
                if a == b && x.transposed() == *y)
            {
                return Err(fail(
                    "HIR Vector transpose consuming orientation/type contract invalid".into(),
                ));
            }
        }
        HirExprKind::MatrixInit {
            rows,
            columns,
            row_ends,
            element_type,
            elements,
        } => {
            for element in elements {
                verify_expr(element, f, sigs, structs, enums, types, fail)?;
            }
            if !valid_matrix_literal_shape(*rows, *columns, row_ends, elements.len())
                || types.matrix_element(e.ty) != Some(*element_type)
                || elements.iter().any(|element| element.ty != *element_type)
                || !types.is_admitted_matrix_element(*element_type)
            {
                return Err(fail(
                    "HIR Matrix literal construction contract invalid".into(),
                ));
            }
        }
        HirExprKind::VectorInit {
            element_type,
            elements,
        } => {
            for element in elements {
                verify_expr(element, f, sigs, structs, enums, types, fail)?;
            }
            if types.vector_element(e.ty) != Some(*element_type)
                || elements.iter().any(|element| element.ty != *element_type)
                || !types.is_admitted_vector_element(*element_type)
            {
                return Err(fail(
                    "HIR Vector literal construction contract invalid".into(),
                ));
            }
        }
        HirExprKind::ArrayInit {
            element_type,
            elements,
        } => {
            for element in elements {
                verify_expr(element, f, sigs, structs, enums, types, fail)?;
            }
            if types.array_element(e.ty) != Some(*element_type)
                || elements.iter().any(|element| element.ty != *element_type)
                || !types.is_admitted_array_element(*element_type)
            {
                return Err(fail(
                    "HIR Array literal construction contract invalid".into(),
                ));
            }
        }
        HirExprKind::ArrayFill {
            element_type,
            length,
            initial,
        } => {
            verify_expr(length, f, sigs, structs, enums, types, fail)?;
            verify_expr(initial, f, sigs, structs, enums, types, fail)?;
            if types.array_element(e.ty) != Some(*element_type)
                || length.ty != TypeId::USIZE
                || initial.ty != *element_type
                || !types.is_admitted_array_element(*element_type)
                || !types.guarantees_copy(*element_type)
            {
                return Err(fail("HIR Array fill construction contract invalid".into()));
            }
        }
        HirExprKind::MatrixRows { source } | HirExprKind::MatrixColumns { source } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            if types.matrix_like_element(source.ty).is_none() || e.ty != TypeId::USIZE {
                return Err(fail("HIR Matrix shape contract invalid".into()));
            }
        }
        HirExprKind::VectorDimension { source } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            if types.vector_like_info(source.ty).is_none() || e.ty != TypeId::USIZE {
                return Err(fail("HIR Vector dimension contract invalid".into()));
            }
        }
        HirExprKind::ArrayLength { source } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            if types.array_element(source.ty).is_none() || e.ty != TypeId::USIZE {
                return Err(fail("HIR Array length contract invalid".into()));
            }
        }
        HirExprKind::ListInit {
            element_type,
            elements,
        } => {
            for element in elements {
                verify_expr(element, f, sigs, structs, enums, types, fail)?;
            }
            if types.list_element(e.ty) != Some(*element_type)
                || elements.iter().any(|element| element.ty != *element_type)
                || !types.is_admitted_list_element(*element_type)
            {
                return Err(fail(
                    "HIR List literal construction contract invalid".into(),
                ));
            }
        }
        HirExprKind::ListSwapRemove {
            source,
            index,
            element_type,
            effect,
            invalidation,
        } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            verify_expr(index, f, sigs, structs, enums, types, fail)?;
            if types.list_element(source.ty) != Some(*element_type)
                || e.ty != *element_type
                || index.ty != TypeId::USIZE
                || *effect != MutationEffect::StableStructuralMutation
                || *invalidation != InvalidationShape::IndexAndTail
                || matches!(
                    source.base,
                    HirPlaceBase::Dereference { mutable: false, .. }
                )
            {
                return Err(fail(
                    "HIR ListSwapRemove writable/index/type/effect contract invalid".into(),
                ));
            }
        }
        HirExprKind::ListRemove {
            source,
            index,
            element_type,
            effect,
            invalidation,
        } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            verify_expr(index, f, sigs, structs, enums, types, fail)?;
            if types.list_element(source.ty) != Some(*element_type)
                || e.ty != *element_type
                || index.ty != TypeId::USIZE
                || *effect != MutationEffect::StableStructuralMutation
                || *invalidation != InvalidationShape::SuffixFrom
                || matches!(
                    source.base,
                    HirPlaceBase::Dereference { mutable: false, .. }
                )
            {
                return Err(fail(
                    "HIR ListRemove writable/index/type/effect contract invalid".into(),
                ));
            }
        }
        HirExprKind::ListPop {
            source,
            element_type,
            effect,
        } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            if types.list_element(source.ty) != Some(*element_type)
                || e.ty != *element_type
                || *effect != MutationEffect::StableStructuralMutation
                || matches!(
                    source.base,
                    HirPlaceBase::Dereference { mutable: false, .. }
                )
            {
                return Err(fail(
                    "HIR ListPop writable/type/effect contract invalid".into(),
                ));
            }
        }
        HirExprKind::ListLength { source } | HirExprKind::ListCapacity { source } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            if types.list_element(source.ty).is_none() || e.ty != TypeId::USIZE {
                return Err(fail("HIR List metadata query contract invalid".into()));
            }
        }
        HirExprKind::MatrixAxisVectorView {
            source,
            fixed_index,
            axis,
            mutable,
            descriptor,
        } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            verify_expr(fixed_index, f, sigs, structs, enums, types, fail)?;
            let element = types
                .matrix_like_element(source.ty)
                .ok_or_else(|| fail("HIR MatrixAxisVectorView source rank/type invalid".into()))?;
            if types.vector_view_info(e.ty) != Some((element, *axis, *mutable))
                || fixed_index.ty != TypeId::USIZE
                || *descriptor != crate::types::MatrixAxisVectorViewDescriptor::derived(*axis)
                || (*mutable
                    && (types.matrix_view_info(source.ty).is_some_and(|(_, m)| !m)
                        || !hir_place_writable(source, f, types, structs, enums)))
            {
                return Err(fail("HIR MatrixAxisVectorView bounds/recipe/orientation/capability contract invalid".into()));
            }
        }
        HirExprKind::VectorView {
            source,
            mutable,
            transpose,
            descriptor,
        } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            let (element, orientation) = types
                .vector_like_info(source.ty)
                .ok_or_else(|| fail("HIR VectorView source invalid".into()))?;
            if types.vector_view_info(e.ty)
                != Some((
                    element,
                    if *transpose {
                        orientation.transposed()
                    } else {
                        orientation
                    },
                    *mutable,
                ))
                || *descriptor
                    != crate::types::VectorViewDescriptor::derived(
                        types.vector_view_info(source.ty).is_some(),
                    )
                || (*mutable
                    && (types
                        .vector_view_info(source.ty)
                        .is_some_and(|(_, _, m)| !m)
                        || !hir_place_writable(source, f, types, structs, enums)))
            {
                return Err(fail(
                    "HIR VectorView stride/type/capability contract invalid".into(),
                ));
            }
        }
        HirExprKind::MatrixView {
            source,
            mutable,
            transpose,
            descriptor,
        } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            let element = types
                .matrix_like_element(source.ty)
                .ok_or_else(|| fail("HIR MatrixView source invalid".into()))?;
            if types.matrix_view_info(e.ty) != Some((element, *mutable))
                || *descriptor
                    != crate::types::MatrixViewDescriptor::derived(
                        types.matrix_view_info(source.ty).is_some(),
                        *transpose,
                    )
                || (*mutable
                    && (types.matrix_view_info(source.ty).is_some_and(|(_, m)| !m)
                        || !hir_place_writable(source, f, types, structs, enums)))
            {
                return Err(fail(
                    "HIR MatrixView stride/type/capability contract invalid".into(),
                ));
            }
        }
        HirExprKind::View { source, mutable } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            let Some(element) = types.owning_contiguous_element(source.ty).filter(|_| {
                types.vector_element(source.ty).is_none()
                    && types.matrix_element(source.ty).is_none()
            }) else {
                return Err(fail("HIR View source is not Buffer/Array/List".into()));
            };
            if types.view_info(e.ty) != Some((element, *mutable)) {
                return Err(fail("HIR View type/capability mismatch".into()));
            }
        }
        HirExprKind::FunctionRef {
            target,
            function_type,
        } => {
            let Some((parameters, result)) = types.function_signature(*function_type) else {
                return Err(fail("HIR FunctionRef has a non-Function type".into()));
            };
            let (target_parameters, target_result) = match (sigs, target) {
                (VerificationSignatures::Concrete(signatures), HirCallTarget::Instance(target)) => {
                    let signature = signatures
                        .get(target.0 as usize)
                        .filter(|signature| signature.id == *target)
                        .ok_or_else(|| fail("HIR FunctionRef target is missing".into()))?;
                    (
                        signature
                            .parameters
                            .iter()
                            .map(|parameter| parameter.ty)
                            .collect::<Vec<_>>(),
                        signature.return_type,
                    )
                }
                (
                    VerificationSignatures::Parametric(signatures),
                    HirCallTarget::Declaration(target),
                ) => {
                    let signature = signatures
                        .get(target.0 as usize)
                        .filter(|signature| signature.id == *target)
                        .ok_or_else(|| fail("HIR FunctionRef declaration is missing".into()))?;
                    if !signature.generic_parameters.is_empty() {
                        return Err(fail(
                            "HIR FunctionRef targets an open generic function".into(),
                        ));
                    }
                    (
                        signature
                            .parameters
                            .iter()
                            .map(|parameter| parameter.ty)
                            .collect::<Vec<_>>(),
                        signature.return_type,
                    )
                }
                _ => return Err(fail("HIR FunctionRef target phase is invalid".into())),
            };
            if e.ty != *function_type || parameters != target_parameters || result != target_result
            {
                return Err(fail("HIR FunctionRef signature mismatch".into()));
            }
        }
        HirExprKind::IndirectCall {
            callee,
            args,
            signature,
            ..
        } => {
            verify_expr(callee, f, sigs, structs, enums, types, fail)?;
            let Some((parameters, result)) = types.function_signature(*signature) else {
                return Err(fail("HIR IndirectCall has a non-Function signature".into()));
            };
            if callee.ty != *signature || e.ty != result || args.len() != parameters.len() {
                return Err(fail("HIR IndirectCall callee/result/arity mismatch".into()));
            }
            for (argument, parameter) in args.iter().zip(parameters) {
                verify_expr(argument, f, sigs, structs, enums, types, fail)?;
                if argument.ty != *parameter {
                    return Err(fail("HIR IndirectCall argument type mismatch".into()));
                }
            }
        }
        HirExprKind::Call {
            call_site,
            callee,
            type_arguments,
            args,
        } => {
            let (return_type, parameters, declaration) = match (sigs, callee) {
                (VerificationSignatures::Concrete(signatures), HirCallTarget::Instance(callee)) => {
                    let s = signatures
                        .get(callee.0 as usize)
                        .ok_or_else(|| fail("HIR callee missing".into()))?;
                    if type_arguments != &s.type_arguments {
                        return Err(fail("HIR call type arguments mismatch".into()));
                    }
                    (
                        s.return_type,
                        s.parameters.iter().map(|p| p.ty).collect::<Vec<_>>(),
                        s.function_id,
                    )
                }
                (
                    VerificationSignatures::Parametric(signatures),
                    HirCallTarget::Declaration(callee),
                ) => {
                    let s = signatures
                        .get(callee.0 as usize)
                        .ok_or_else(|| fail("HIR generic callee missing".into()))?;
                    if type_arguments.len() != s.generic_parameters.len() {
                        return Err(fail("HIR generic call arity invalid".into()));
                    }
                    validate_generic_constraints(
                        types,
                        &s.generic_parameters,
                        type_arguments,
                        &s.name,
                        structs,
                        enums,
                        e.span,
                        false,
                    )
                    .map_err(|_| {
                        fail("HIR generic call missing required capability guarantee".into())
                    })?;
                    let substitution = Substitution::new(
                        s.generic_parameters.iter().map(|p| p.id),
                        type_arguments.iter().copied(),
                    );
                    let substitute = |ty| {
                        types
                            .substituted_existing(ty, &substitution)
                            .map_err(|_| fail("HIR generic call substitution incomplete".into()))
                    };
                    (
                        substitute(s.return_type)?,
                        s.parameters
                            .iter()
                            .map(|p| substitute(p.ty))
                            .collect::<Result<Vec<_>, _>>()?,
                        s.id,
                    )
                }
                _ => {
                    return Err(fail(
                        "HIR call target does not match verification stage".into(),
                    ));
                }
            };
            if return_type != e.ty || args.len() != parameters.len() {
                return Err(fail("HIR call mismatch".into()));
            }
            let mut bindings = BTreeSet::new();
            let mut saw_default = false;
            for (index, (a, ty)) in args.iter().zip(parameters).enumerate() {
                if f.locals.get(a.binding.0 as usize).map(|local| local.ty) != Some(a.ty)
                    || a.ty != ty
                    || !bindings.insert(a.binding)
                {
                    return Err(fail("HIR call argument binding/type mismatch".into()));
                }
                match a.origin {
                    HirCallArgumentOrigin::Explicit { .. } if saw_default => {
                        return Err(fail(
                            "HIR explicit argument follows a defaulted argument".into(),
                        ));
                    }
                    HirCallArgumentOrigin::Explicit { .. } => {}
                    HirCallArgumentOrigin::Defaulted {
                        declaration: owner,
                        parameter_index,
                        ..
                    } if owner == declaration && parameter_index as usize == index => {
                        saw_default = true;
                    }
                    HirCallArgumentOrigin::Defaulted { .. } => {
                        return Err(fail("HIR default argument provenance mismatch".into()));
                    }
                }
                if matches!(
                    a.initializer.kind,
                    HirExprKind::CallScopedSharedBorrow { .. }
                ) {
                    verify_call_borrow(
                        &a.initializer,
                        *call_site,
                        index,
                        f,
                        sigs,
                        structs,
                        enums,
                        types,
                        fail,
                    )?;
                } else {
                    verify_expr(&a.initializer, f, sigs, structs, enums, types, fail)?;
                }
                if a.initializer.ty != ty {
                    return Err(fail("HIR argument mismatch".into()));
                }
            }
        }
        HirExprKind::StructInit { struct_id, fields } => {
            let Some(info) = structs
                .get(struct_id.0 as usize)
                .filter(|info| info.id == *struct_id)
            else {
                return Err(fail("HIR struct initializer has unknown identity".into()));
            };
            if types.struct_id(e.ty) != Some(*struct_id) || fields.len() != info.fields.len() {
                return Err(fail("HIR struct initializer arity/type mismatch".into()));
            }
            for ((field_id, value), declared) in fields.iter().zip(&info.fields) {
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                let expected = concrete_member_type(types, e.ty, declared.ty, structs, enums)
                    .ok_or_else(|| fail("HIR struct substitution incomplete".into()))?;
                if *field_id != declared.id || value.ty != expected {
                    return Err(fail("HIR struct initializer field mismatch".into()));
                }
            }
        }
        HirExprKind::EnumInit {
            enum_id,
            variant_id,
            payloads,
        } => {
            let Some(info) = enums
                .get(enum_id.0 as usize)
                .filter(|info| info.id == *enum_id)
            else {
                return Err(fail("HIR enum initializer has unknown identity".into()));
            };
            let Some(variant) = info
                .variants
                .get(variant_id.index as usize)
                .filter(|variant| variant.id == *variant_id)
            else {
                return Err(fail("HIR enum initializer variant mismatch".into()));
            };
            if types.enum_id(e.ty) != Some(*enum_id) || payloads.len() != variant.payloads.len() {
                return Err(fail("HIR enum initializer arity/type mismatch".into()));
            }
            for (value, declared) in payloads.iter().zip(&variant.payloads) {
                verify_expr(value, f, sigs, structs, enums, types, fail)?;
                let expected = concrete_member_type(types, e.ty, declared.ty, structs, enums)
                    .ok_or_else(|| fail("HIR enum substitution incomplete".into()))?;
                if value.ty != expected {
                    return Err(fail("HIR enum initializer payload mismatch".into()));
                }
            }
        }
        HirExprKind::Coerce { kind, operand } => {
            verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            let ok = match (
                kind,
                types.integer_info(operand.ty),
                types.integer_info(e.ty),
            ) {
                (CoercionKind::SignExtend, Some(a), Some(b)) => a.is_signed() && a.can_widen_to(b),
                (CoercionKind::ZeroExtend, Some(a), Some(b)) => !a.is_signed() && a.can_widen_to(b),
                (CoercionKind::FloatExtend, _, _)
                    if operand.ty == TypeId::FLOAT32 && e.ty == TypeId::FLOAT64 =>
                {
                    true
                }
                _ => false,
            };
            if !ok {
                return Err(fail("HIR coercion invalid".into()));
            }
        }
        HirExprKind::ExplicitCast {
            kind,
            source_type,
            target_type,
            operand,
        } => {
            verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            if operand.ty != *source_type
                || e.ty != *target_type
                || select_cast_kind(
                    types,
                    *source_type,
                    *target_type,
                    TargetProperties::LINUX_X86_64,
                ) != Some(*kind)
            {
                return Err(fail("HIR explicit cast contract invalid".into()));
            }
        }
        HirExprKind::Unary { op, operand } => {
            verify_expr(operand, f, sigs, structs, enums, types, fail)?;
            let ok = match op {
                HirUnaryOp::NegateIntegerChecked => types
                    .integer_info(operand.ty)
                    .is_some_and(IntegerType::is_signed),
                HirUnaryOp::NegateFloat => types.float_info(operand.ty).is_some(),
            } && e.ty == operand.ty;
            if !ok {
                return Err(fail("HIR unary invalid".into()));
            }
        }
        HirExprKind::AlgebraicValue { capability } => {
            if matches!(sigs, VerificationSignatures::Concrete(_))
                || types.generic_param(e.ty).is_none()
                || !types.guarantees_capability(e.ty, Capability::Algebraic(*capability))
            {
                return Err(fail("HIR unresolved/invalid algebraic value".into()));
            }
        }
        HirExprKind::AlgebraicProduct {
            left,
            right,
            element_type,
            product_op,
            product,
        } => {
            verify_expr(left, f, sigs, structs, enums, types, fail)?;
            verify_expr(right, f, sigs, structs, enums, types, fail)?;
            if let AlgebraicProductKind::MatrixMatrix { zero, .. } = product {
                let (expected_op, expected) =
                    matrix_matrix_recipe(types, *element_type, e.span).map_err(fail)?;
                verify_expr(zero, f, sigs, structs, enums, types, fail)?;
                let mut normalized = product.clone();
                if let AlgebraicProductKind::MatrixMatrix { zero: z, .. } = &mut normalized {
                    z.span = e.span;
                }
                if normalized != expected
                    || *product_op != expected_op
                    || types.matrix_like_element(left.ty) != Some(*element_type)
                    || types.matrix_like_element(right.ty) != Some(*element_type)
                    || types.matrix_element(e.ty) != Some(*element_type)
                    || (matches!(sigs, VerificationSignatures::Concrete(_))
                        && matches!(product_op, MathElementOp::Behavioral(_)))
                    || [left, right].iter().any(|x| {
                        !types.is_copy(x.ty)
                            && matches!(
                                x.kind,
                                HirExprKind::Local(_) | HirExprKind::Move(_) | HirExprKind::Load(_)
                            )
                    })
                {
                    return Err(fail("HIR Matrix algebraic multiplication source/result/three extents/shape/operations/read-only metadata invalid".into()));
                }
                return Ok(());
            }
            if let AlgebraicProductKind::MatrixVector {
                matrix_side, zero, ..
            } = product
            {
                let (expected_op, expected) =
                    matrix_vector_recipe(types, *element_type, *matrix_side, e.span)
                        .map_err(fail)?;
                verify_expr(zero, f, sigs, structs, enums, types, fail)?;
                let (matrix, vector, orientation) = if *matrix_side == ScalarSide::Left {
                    (left, right, crate::types::Orientation::Column)
                } else {
                    (right, left, crate::types::Orientation::Row)
                };
                // Spans are not evidence. Compare the symbolic/concrete zero's type and value separately.
                let mut normalized = product.clone();
                if let AlgebraicProductKind::MatrixVector { zero: z, .. } = &mut normalized {
                    z.span = e.span;
                }
                if normalized != expected
                    || *product_op != expected_op
                    || types.matrix_like_element(matrix.ty) != Some(*element_type)
                    || types.vector_like_info(vector.ty) != Some((*element_type, orientation))
                    || (types.vector_element(e.ty) != Some(*element_type)
                        || types.vector_like_info(e.ty) != Some((*element_type, orientation)))
                    || (matches!(sigs, VerificationSignatures::Concrete(_))
                        && matches!(product_op, MathElementOp::Behavioral(_)))
                    || [left, right].iter().any(|x| {
                        !types.is_copy(x.ty)
                            && matches!(
                                x.kind,
                                HirExprKind::Local(_) | HirExprKind::Move(_) | HirExprKind::Load(_)
                            )
                    })
                {
                    return Err(fail("HIR algebraic Matrix/Vector multiplication orientation/result/contraction/shape/operations/read-only metadata invalid".into()));
                }
                return Ok(());
            }
            let inner = matches!(product, AlgebraicProductKind::Inner { .. });
            let lo = if inner {
                crate::types::Orientation::Row
            } else {
                crate::types::Orientation::Column
            };
            let ro = if inner {
                crate::types::Orientation::Column
            } else {
                crate::types::Orientation::Row
            };
            let (expected_op, expected_product) =
                vector_product_recipe(types, *element_type, inner, e.span).map_err(fail)?;
            let product_valid = match (product, expected_product) {
                (
                    AlgebraicProductKind::Inner {
                        shape_check,
                        accumulate_op,
                        zero,
                    },
                    AlgebraicProductKind::Inner {
                        shape_check: sc,
                        accumulate_op: ao,
                        zero: z,
                    },
                ) => {
                    verify_expr(zero, f, sigs, structs, enums, types, fail)?;
                    *shape_check == sc
                        && *accumulate_op == ao
                        && zero.ty == z.ty
                        && zero.kind == z.kind
                }
                (
                    AlgebraicProductKind::Outer { rows, columns },
                    AlgebraicProductKind::Outer {
                        rows: r,
                        columns: c,
                    },
                ) => *rows == r && *columns == c,
                _ => false,
            };
            if types.vector_like_info(left.ty) != Some((*element_type, lo))
                || types.vector_like_info(right.ty) != Some((*element_type, ro))
                || (if inner {
                    e.ty != *element_type
                } else {
                    types.matrix_element(e.ty) != Some(*element_type)
                })
                || *product_op != expected_op
                || !product_valid
                || (matches!(sigs, VerificationSignatures::Concrete(_))
                    && matches!(product_op, MathElementOp::Behavioral(_)))
                || [left, right].iter().any(|x| {
                    !types.is_copy(x.ty)
                        && matches!(
                            x.kind,
                            HirExprKind::Local(_) | HirExprKind::Move(_) | HirExprKind::Load(_)
                        )
                })
            {
                return Err(fail("HIR algebraic multiplication orientation/result/operation/shape/read-only metadata invalid".into()));
            }
        }
        HirExprKind::VectorScalarMultiply {
            left,
            right,
            scalar_side,
            element_type,
            op,
            ..
        }
        | HirExprKind::MatrixScalarMultiply {
            left,
            right,
            scalar_side,
            element_type,
            op,
        } => {
            verify_expr(left, f, sigs, structs, enums, types, fail)?;
            verify_expr(right, f, sigs, structs, enums, types, fail)?;
            let (scalar, source) = if *scalar_side == ScalarSide::Left {
                (left, right)
            } else {
                (right, left)
            };
            let valid_family = match &e.kind {
                HirExprKind::VectorScalarMultiply { orientation, .. } => {
                    types.vector_like_info(source.ty) == Some((*element_type, *orientation))
                        && types.get(e.ty)
                            == Some(&TypeData::Vector {
                                element: *element_type,
                                orientation: *orientation,
                            })
                }
                _ => {
                    types.matrix_like_element(source.ty) == Some(*element_type)
                        && types.matrix_element(e.ty) == Some(*element_type)
                }
            };
            verify_math_element_op(types, *element_type, *op, BehavioralCapability::Mul, sigs)
                .map_err(fail)?;
            if !valid_family
                || scalar.ty != *element_type
                || (!types.is_copy(source.ty)
                    && matches!(
                        source.kind,
                        HirExprKind::Local(_) | HirExprKind::Move(_) | HirExprKind::Load(_)
                    ))
            {
                return Err(fail(
                    "HIR scalar multiplication side/type/read-only result contract invalid".into(),
                ));
            }
        }
        HirExprKind::VectorElementwiseBinary {
            shape_check,
            source_op,
            left,
            right,
            element_type,
            op,
            ..
        }
        | HirExprKind::MatrixElementwiseBinary {
            shape_check,
            source_op,
            left,
            right,
            element_type,
            op,
        } => {
            verify_expr(left, f, sigs, structs, enums, types, fail)?;
            verify_expr(right, f, sigs, structs, enums, types, fail)?;
            let valid_types = match &e.kind {
                HirExprKind::VectorElementwiseBinary { orientation, .. } => {
                    *shape_check == MathShapeCheck::VectorDimension
                        && types.vector_like_info(left.ty) == Some((*element_type, *orientation))
                        && types.vector_like_info(right.ty) == Some((*element_type, *orientation))
                        && types.get(e.ty)
                            == Some(&TypeData::Vector {
                                element: *element_type,
                                orientation: *orientation,
                            })
                }
                _ => {
                    *shape_check == MathShapeCheck::MatrixRowsThenColumns
                        && types.matrix_like_element(left.ty) == Some(*element_type)
                        && types.matrix_like_element(right.ty) == Some(*element_type)
                        && types.matrix_element(e.ty) == Some(*element_type)
                }
            };
            let behavior = match source_op {
                AstBinaryOp::Add => BehavioralCapability::Add,
                AstBinaryOp::Subtract => BehavioralCapability::Sub,
                _ => return Err(fail("HIR elementwise source operator invalid".into())),
            };
            verify_math_element_op(types, *element_type, *op, behavior, sigs).map_err(fail)?;
            if !valid_types
                || (!types.is_copy(left.ty)
                    && matches!(
                        left.kind,
                        HirExprKind::Local(_) | HirExprKind::Move(_) | HirExprKind::Load(_)
                    ))
                || (!types.is_copy(right.ty)
                    && matches!(
                        right.kind,
                        HirExprKind::Local(_) | HirExprKind::Move(_) | HirExprKind::Load(_)
                    ))
            {
                return Err(fail(
                    "HIR elementwise type/op/read-only ShapeMismatch contract invalid".into(),
                ));
            }
        }
        HirExprKind::CapabilityBinary {
            behavior,
            left,
            right,
        } => {
            verify_expr(left, f, sigs, structs, enums, types, fail)?;
            verify_expr(right, f, sigs, structs, enums, types, fail)?;
            if left.ty != right.ty || e.ty != left.ty || !types.guarantees_behavior(e.ty, *behavior)
            {
                return Err(fail(
                    "HIR CapabilityBinary homogeneous type/behavior guarantee invalid".into(),
                ));
            }
            if matches!(sigs, VerificationSignatures::Concrete(_)) {
                return Err(fail(
                    "unresolved CapabilityBinary reached concrete HIR".into(),
                ));
            }
        }
        HirExprKind::Binary { op, left, right } => {
            verify_expr(left, f, sigs, structs, enums, types, fail)?;
            verify_expr(right, f, sigs, structs, enums, types, fail)?;
            if left.ty != right.ty {
                return Err(fail("HIR binary operand mismatch".into()));
            }
            let ok = match op {
                HirBinaryOp::AddIntegerChecked
                | HirBinaryOp::SubtractIntegerChecked
                | HirBinaryOp::MultiplyIntegerChecked => {
                    types.integer_info(left.ty).is_some() && e.ty == left.ty
                }
                HirBinaryOp::DivideIntegerSignedChecked
                | HirBinaryOp::RemainderIntegerSignedChecked => {
                    types
                        .integer_info(left.ty)
                        .is_some_and(IntegerType::is_signed)
                        && e.ty == left.ty
                }
                HirBinaryOp::DivideIntegerUnsignedChecked
                | HirBinaryOp::RemainderIntegerUnsignedChecked => {
                    types
                        .integer_info(left.ty)
                        .is_some_and(|integer| !integer.is_signed())
                        && e.ty == left.ty
                }
                HirBinaryOp::AddFloat
                | HirBinaryOp::SubtractFloat
                | HirBinaryOp::MultiplyFloat
                | HirBinaryOp::DivideFloat => {
                    types.float_info(left.ty).is_some() && e.ty == left.ty
                }
                HirBinaryOp::Less
                | HirBinaryOp::LessEqual
                | HirBinaryOp::Greater
                | HirBinaryOp::GreaterEqual => types.is_numeric(left.ty) && e.ty == TypeId::BOOL,
                HirBinaryOp::Equal | HirBinaryOp::NotEqual => {
                    (left.ty == TypeId::BOOL
                        || types.is_numeric(left.ty)
                        || matches!(
                            classify_enum_equality(left.ty, right.ty, enums, types),
                            EnumEqualityClassification::Admitted { .. }
                        ))
                        && e.ty == TypeId::BOOL
                }
            };
            if !ok {
                return Err(fail("HIR binary invalid".into()));
            }
        }
        _ => {}
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn verify_call_borrow(
    expression: &HirExpr,
    expected_site: CallSiteId,
    expected_index: usize,
    function: &VerificationFunction<'_>,
    signatures: VerificationSignatures<'_>,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let HirExprKind::CallScopedSharedBorrow {
        call_site,
        argument_index,
        pointee_type,
        reference_type,
        source,
        origin,
    } = &expression.kind
    else {
        return Err(fail("HIR argument is not a call borrow".into()));
    };
    if *call_site != expected_site
        || *argument_index as usize != expected_index
        || expression.ty != *reference_type
        || types.reference_info(*reference_type) != Some((*pointee_type, false))
    {
        return Err(fail(
            "HIR call borrow identity/index/pointee/reference contract invalid".into(),
        ));
    }
    match source {
        CallBorrowSource::Place(place) => {
            verify_place(place, function, signatures, structs, enums, types, fail)?;
            if place.ty != *pointee_type {
                return Err(fail("HIR call borrow Place type mismatch".into()));
            }
            if let HirPlaceBase::Local(local) = place.base
                && !place
                    .projections
                    .iter()
                    .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
                && !function.locals[local.0 as usize].address_taken
            {
                return Err(fail(
                    "HIR call-borrowed local is not marked address-taken".into(),
                ));
            }
        }
        CallBorrowSource::Temporary(initializer) => {
            verify_expr(
                initializer,
                function,
                signatures,
                structs,
                enums,
                types,
                fail,
            )?;
            if initializer.ty != *pointee_type
                || matches!(initializer.kind, HirExprKind::Coerce { .. })
                || *origin != CallBorrowOrigin::Implicit
            {
                return Err(fail(
                    "HIR call temporary requires one exact unconverted T initializer".into(),
                ));
            }
        }
    }
    Ok(())
}

fn hir_const_inline_root(place: &HirPlace, f: &VerificationFunction<'_>) -> Option<LocalId> {
    let HirPlaceBase::Local(local) = place.base else {
        return None;
    };
    let info = f.locals.get(local.0 as usize)?;
    (info.mutability == crate::BindingMutability::Const
        && !place
            .projections
            .iter()
            .any(|projection| matches!(projection, HirPlaceProjection::Index { .. })))
    .then_some(local)
}

fn hir_place_writable(
    place: &HirPlace,
    f: &VerificationFunction<'_>,
    types: &TypeArena,
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> bool {
    let mut ty = match &place.base {
        HirPlaceBase::Local(local) => f.locals[local.0 as usize].ty,
        HirPlaceBase::Dereference { reference, mutable } => {
            if !mutable {
                return false;
            }
            let Some((pointee, true)) = types.reference_info(reference.ty) else {
                return false;
            };
            pointee
        }
    };
    for projection in &place.projections {
        match projection {
            HirPlaceProjection::Index { element_type, .. } => {
                if types.borrowed_view_info(ty).is_some_and(|(_, m)| !m) {
                    return false;
                }
                ty = *element_type;
            }
            HirPlaceProjection::Field(field) => {
                let Some(owner) = types.struct_id(ty) else {
                    return false;
                };
                let Some(info) = structs
                    .get(owner.0 as usize)
                    .and_then(|s| s.fields.iter().find(|f| f.id == *field))
                else {
                    return false;
                };
                let Some(member) = concrete_member_type(types, ty, info.ty, structs, enums) else {
                    return false;
                };
                ty = member;
            }
        }
    }
    true
}

fn verify_place(
    place: &HirPlace,
    function: &VerificationFunction<'_>,
    sigs: VerificationSignatures<'_>,
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    let mut ty = match &place.base {
        HirPlaceBase::Local(local) => function
            .locals
            .get(local.0 as usize)
            .map(|local| local.ty)
            .ok_or_else(|| fail("HIR place has unknown local".into()))?,
        HirPlaceBase::Dereference { reference, mutable } => {
            verify_expr(reference, function, sigs, structs, enums, types, fail)?;
            let Some((pointee, capability)) = types.reference_info(reference.ty) else {
                return Err(fail("HIR place dereferences a non-reference".into()));
            };
            if capability != *mutable {
                return Err(fail("HIR dereference capability cache is invalid".into()));
            }
            pointee
        }
    };
    if !types.is_valid(place.ty) || !types.is_valid(ty) {
        return Err(fail("HIR place references invalid TypeId".into()));
    }
    for projection in &place.projections {
        match projection {
            HirPlaceProjection::Field(field_id) => {
                let Some(owner) = types.struct_id(ty) else {
                    return Err(fail("HIR place projects a non-struct".into()));
                };
                let Some(field) = structs
                    .get(owner.0 as usize)
                    .and_then(|info| info.fields.iter().find(|field| field.id == *field_id))
                else {
                    return Err(fail("HIR place field does not belong to struct".into()));
                };
                ty = concrete_member_type(types, ty, field.ty, structs, &[])
                    .ok_or_else(|| fail("HIR place substitution incomplete".into()))?;
            }
            HirPlaceProjection::Index {
                index,
                column,
                element_type,
                checked,
                semantics,
            } => {
                verify_expr(index, function, sigs, structs, enums, types, fail)?;
                if let Some(column) = column {
                    verify_expr(column, function, sigs, structs, enums, types, fail)?;
                }
                let element = types
                    .buffer_element(ty)
                    .or_else(|| types.array_element(ty))
                    .or_else(|| types.vector_element(ty))
                    .or_else(|| types.matrix_element(ty))
                    .or_else(|| types.list_element(ty))
                    .or_else(|| types.borrowed_view_info(ty).map(|(element, _)| element))
                    .ok_or_else(|| fail("HIR index projection has non-contiguous base".into()))?;
                if column.is_some() != (types.matrix_like_element(ty).is_some())
                    || column.as_ref().is_some_and(|c| c.ty != TypeId::USIZE)
                    || index.ty != TypeId::USIZE
                    || element != *element_type
                    || !*checked
                    || types.index_semantics(ty) != Some(*semantics)
                {
                    return Err(fail("HIR index projection contract invalid".into()));
                }
                ty = element;
            }
        }
    }
    if ty != place.ty {
        return Err(fail("HIR place cached type is invalid".into()));
    }
    Ok(())
}

fn concrete_member_type(
    types: &TypeArena,
    aggregate: TypeId,
    member: TypeId,
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> Option<TypeId> {
    let (parameters, arguments) = match types.get(aggregate)? {
        TypeData::StructInstance(id, args) => (
            &structs.get(id.0 as usize)?.generic_parameters,
            types.arguments(*args)?,
        ),
        TypeData::EnumInstance(id, args) => (
            &enums.get(id.0 as usize)?.generic_parameters,
            types.arguments(*args)?,
        ),
        _ => return Some(member),
    };
    let substitution = Substitution::new(
        parameters.iter().map(|parameter| parameter.id),
        arguments.iter().copied(),
    );
    types.substituted_existing(member, &substitution).ok()
}
fn statement_returns(s: &HirStmt) -> bool {
    match &s.kind {
        HirStmtKind::Return { .. } | HirStmtKind::Throw { .. } | HirStmtKind::Rethrow { .. } => {
            true
        }
        HirStmtKind::If {
            then_block,
            else_block: Some(e),
            ..
        } => definitely_returns(then_block) && definitely_returns(e),
        HirStmtKind::Match { arms, .. } => {
            !arms.is_empty() && arms.iter().all(|arm| definitely_returns(&arm.body))
        }
        HirStmtKind::Try { body, catches, .. } => {
            definitely_returns(body) && catches.iter().all(|catch| definitely_returns(&catch.body))
        }
        _ => false,
    }
}
fn definitely_returns(b: &HirBlock) -> bool {
    b.statements.last().is_some_and(statement_returns)
}

fn statement_abrupt(statement: &HirStmt) -> bool {
    match &statement.kind {
        HirStmtKind::Return { .. }
        | HirStmtKind::Break { .. }
        | HirStmtKind::Continue { .. }
        | HirStmtKind::Throw { .. }
        | HirStmtKind::Rethrow { .. } => true,
        HirStmtKind::If {
            then_block,
            else_block: Some(else_block),
            ..
        } => definitely_abrupt(then_block) && definitely_abrupt(else_block),
        HirStmtKind::Match { arms, .. } => {
            !arms.is_empty() && arms.iter().all(|arm| definitely_abrupt(&arm.body))
        }
        HirStmtKind::Try { body, catches, .. } => {
            definitely_abrupt(body)
                && (catches.is_empty()
                    || catches.iter().all(|catch| definitely_abrupt(&catch.body)))
        }
        _ => false,
    }
}

fn definitely_abrupt(block: &HirBlock) -> bool {
    block.statements.last().is_some_and(statement_abrupt)
}

fn verify_finally_identities(
    block: &HirBlock,
    fail: &impl Fn(String) -> Vec<Diagnostic>,
) -> Result<(), Vec<Diagnostic>> {
    fn collect(block: &HirBlock, ids: &mut Vec<FinallyId>, loops: &mut Vec<LoopId>) {
        for statement in &block.statements {
            match &statement.kind {
                HirStmtKind::If {
                    then_block,
                    else_block,
                    ..
                } => {
                    collect(then_block, ids, loops);
                    if let Some(else_block) = else_block {
                        collect(else_block, ids, loops);
                    }
                }
                HirStmtKind::While { body, .. } => collect(body, ids, loops),
                HirStmtKind::ForRange { loop_id, body, .. }
                | HirStmtKind::ForCollection { loop_id, body, .. } => {
                    loops.push(*loop_id);
                    collect(body, ids, loops);
                }
                HirStmtKind::Match { arms, .. } => {
                    for arm in arms {
                        collect(&arm.body, ids, loops);
                    }
                }
                HirStmtKind::Try {
                    body,
                    catches,
                    finally,
                } => {
                    collect(body, ids, loops);
                    for catch in catches {
                        collect(&catch.body, ids, loops);
                    }
                    if let Some(finally) = finally {
                        ids.push(finally.id);
                        collect(&finally.body, ids, loops);
                    }
                }
                _ => {}
            }
        }
    }

    let mut ids = Vec::new();
    let mut loops = Vec::new();
    collect(block, &mut ids, &mut loops);
    ids.sort();
    if ids
        .iter()
        .enumerate()
        .any(|(index, id)| id.0 as usize != index)
    {
        return Err(fail("HIR finally identities are not canonical".into()));
    }
    loops.sort();
    if loops
        .iter()
        .enumerate()
        .any(|(index, id)| id.0 as usize != index)
    {
        return Err(fail("HIR loop identities are not canonical".into()));
    }
    Ok(())
}

fn block_may_throw_or_transfer(block: &HirBlock) -> bool {
    block.statements.iter().any(|statement| {
        matches!(
            statement.kind,
            HirStmtKind::Return { .. }
                | HirStmtKind::Break { .. }
                | HirStmtKind::Continue { .. }
                | HirStmtKind::Throw { .. }
                | HirStmtKind::Rethrow { .. }
        ) || {
            let debug = format!("{:?}", statement.kind);
            debug.contains("Call") || debug.contains("Construct")
        } || match &statement.kind {
            HirStmtKind::If {
                then_block,
                else_block,
                ..
            } => {
                block_may_throw_or_transfer(then_block)
                    || else_block.as_ref().is_some_and(block_may_throw_or_transfer)
            }
            HirStmtKind::While { body, .. }
            | HirStmtKind::ForRange { body, .. }
            | HirStmtKind::ForCollection { body, .. } => block_may_throw_or_transfer(body),
            HirStmtKind::Match { arms, .. } => arms
                .iter()
                .any(|arm| block_may_throw_or_transfer(&arm.body)),
            HirStmtKind::Try {
                body,
                catches,
                finally,
            } => {
                block_may_throw_or_transfer(body)
                    || catches
                        .iter()
                        .any(|catch| block_may_throw_or_transfer(&catch.body))
                    || finally
                        .as_ref()
                        .is_some_and(|finally| block_may_throw_or_transfer(&finally.body))
            }
            _ => false,
        }
    })
}

fn ast_expr_has_call(expr: &AstExpr) -> bool {
    match &expr.kind {
        AstExprKind::Call { .. }
        | AstExprKind::QualifiedCall { .. }
        | AstExprKind::VariantCall { .. }
        | AstExprKind::MethodCall { .. } => true,
        AstExprKind::CollectionLiteral(values) => values.iter().any(ast_expr_has_call),
        AstExprKind::MathematicalLiteral { rows } => rows.iter().flatten().any(ast_expr_has_call),
        AstExprKind::Interpolation(fragments) => fragments.iter().any(|fragment| match fragment {
            crate::AstInterpolationFragment::Hole { expression, .. } => {
                ast_expr_has_call(expression)
            }
            crate::AstInterpolationFragment::Text { .. } => false,
        }),
        AstExprKind::Field { base, .. } => ast_expr_has_call(base),
        AstExprKind::Index { base, indices } => {
            ast_expr_has_call(base) || indices.iter().any(ast_expr_has_call)
        }
        AstExprKind::Unary { operand, .. } => ast_expr_has_call(operand),
        AstExprKind::Binary { left, right, .. } => {
            ast_expr_has_call(left) || ast_expr_has_call(right)
        }
        AstExprKind::Range { start, step, end } => {
            ast_expr_has_call(start)
                || step.as_deref().is_some_and(ast_expr_has_call)
                || ast_expr_has_call(end)
        }
        AstExprKind::Integer(_)
        | AstExprKind::Float(_)
        | AstExprKind::String(_)
        | AstExprKind::Char(_)
        | AstExprKind::Bool(_)
        | AstExprKind::Null
        | AstExprKind::Name(_)
        | AstExprKind::QualifiedName { .. } => false,
    }
}

fn ast_block_has_call(block: &AstBlock) -> bool {
    block
        .statements
        .iter()
        .any(|statement| match &statement.kind {
            AstStmtKind::Local { initializer, .. } => ast_expr_has_call(initializer),
            AstStmtKind::Assign { place, value } => {
                ast_expr_has_call(place) || ast_expr_has_call(value)
            }
            AstStmtKind::Expr(expr) => ast_expr_has_call(expr),
            AstStmtKind::Return(expr) => expr.as_ref().is_some_and(ast_expr_has_call),
            AstStmtKind::If {
                condition,
                then_block,
                else_block,
            } => {
                ast_expr_has_call(condition)
                    || ast_block_has_call(then_block)
                    || else_block.as_ref().is_some_and(ast_block_has_call)
            }
            AstStmtKind::While { condition, body } => {
                ast_expr_has_call(condition) || ast_block_has_call(body)
            }
            AstStmtKind::ForIn { iterable, body, .. } => {
                ast_expr_has_call(iterable) || ast_block_has_call(body)
            }
            AstStmtKind::Match {
                scrutinee, arms, ..
            } => {
                ast_expr_has_call(scrutinee) || arms.iter().any(|arm| ast_block_has_call(&arm.body))
            }
            AstStmtKind::Try {
                body,
                catches,
                finally,
            } => {
                ast_block_has_call(body)
                    || catches.iter().any(|catch| ast_block_has_call(&catch.body))
                    || finally.as_ref().is_some_and(ast_block_has_call)
            }
            AstStmtKind::Throw(value) => value.as_ref().is_some_and(ast_expr_has_call),
            AstStmtKind::Break | AstStmtKind::Continue => false,
        })
}

fn valid_matrix_literal_shape(rows: u64, columns: u64, row_ends: &[u64], count: usize) -> bool {
    rows.checked_mul(columns) == u64::try_from(count).ok()
        && (rows == 0) == (columns == 0)
        && u64::try_from(row_ends.len()).ok() == Some(rows)
        && row_ends
            .iter()
            .enumerate()
            .all(|(i, end)| (i as u64 + 1).checked_mul(columns) == Some(*end))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{SourceFile, parse_source};
    fn check(s: &str) -> Result<TypedHir, Vec<Diagnostic>> {
        analyze(parse_source(&SourceFile::new("test.ae", s)).unwrap())
    }
    #[test]
    fn iteration_v1_hir_corruptions_fail_closed() {
        let hir = check("int main(){int x=0;for(i in 0:2:6){x=x+i;}return x;}").unwrap();
        verify_hir(&hir).unwrap();
        for case in 0..3 {
            let mut bad = hir.clone();
            let HirStmtKind::ForRange {
                loop_id,
                item_type,
                step,
                ..
            } = &mut bad.functions[0].body.statements[1].kind
            else {
                panic!("expected range loop")
            };
            match case {
                0 => *loop_id = LoopId(9),
                1 => *item_type = TypeId::INT32,
                2 => step.kind = HirExprKind::Int(0),
                _ => unreachable!(),
            }
            assert!(verify_hir(&bad).is_err());
        }
    }
    #[test]
    fn call_scoped_shared_borrow_hir_corruptions_fail_closed() {
        let hir =
            check("int read(ref int x){return *x;}int main(){int x=7;int y=read(x);return y;}")
                .unwrap();
        verify_hir(&hir).unwrap();
        for case in 0..4 {
            let mut bad = hir.clone();
            let HirStmtKind::Local { initializer, .. } =
                &mut bad.functions[1].body.statements[1].kind
            else {
                panic!("expected call result local")
            };
            let HirExprKind::Call {
                call_site, args, ..
            } = &mut initializer.kind
            else {
                panic!("expected direct call")
            };
            let argument_span = args[0].initializer.span;
            let HirExprKind::CallScopedSharedBorrow {
                call_site: borrow_site,
                argument_index,
                pointee_type: _,
                reference_type,
                source,
                origin,
            } = &mut args[0].initializer.kind
            else {
                panic!("expected implicit borrow")
            };
            match case {
                0 => *borrow_site = CallSiteId(call_site.0 + 1),
                1 => *argument_index = 1,
                2 => *reference_type = TypeId::BOOL,
                3 => {
                    let CallBorrowSource::Place(place) = source else {
                        unreachable!()
                    };
                    *source = CallBorrowSource::Temporary(Box::new(HirExpr {
                        kind: HirExprKind::Int(7),
                        ty: place.ty,
                        span: argument_span,
                    }));
                    *origin = CallBorrowOrigin::Explicit;
                }
                _ => unreachable!(),
            }
            assert!(verify_hir(&bad).is_err());
        }
    }
    #[test]
    fn iteration_v2_hir_corruptions_fail_closed() {
        let hir = check(
            "int main(){Array<int> values={1,2};int sum=0;for(x in values){sum=sum+x;}return sum;}",
        )
        .unwrap();
        verify_hir(&hir).unwrap();
        for case in 0..4 {
            let mut bad = hir.clone();
            let HirStmtKind::ForCollection {
                item_type,
                binding_type,
                category,
                structural_borrow,
                ..
            } = &mut bad.functions[0].body.statements[2].kind
            else {
                panic!("expected collection loop")
            };
            match case {
                0 => *item_type = TypeId::INT32,
                1 => *binding_type = TypeId::INT32,
                2 => *category = IterationBindingCategory::CopyValue,
                3 => *structural_borrow = true,
                _ => unreachable!(),
            }
            if case == 2 {
                let HirStmtKind::ForCollection { source, .. } =
                    &mut bad.functions[0].body.statements[2].kind
                else {
                    unreachable!()
                };
                let CollectionIterationSource::Borrowed(place) = source else {
                    unreachable!()
                };
                place.ty = TypeId::INT64;
            }
            assert!(verify_hir(&bad).is_err());
        }
    }
    #[test]
    fn iteration_v3_shared_borrow_hir_corruptions_fail_closed() {
        let hir = check(
            "int main(){Array<string> values={\"x\"};for(word in values){println(*word);}return 0;}",
        )
        .unwrap();
        verify_hir(&hir).unwrap();
        for case in 0..3 {
            let mut bad = hir.clone();
            let HirStmtKind::ForCollection {
                item_type,
                binding_type,
                category,
                ..
            } = &mut bad.functions[0].body.statements[1].kind
            else {
                panic!("expected shared collection loop")
            };
            match case {
                0 => *item_type = TypeId::INT64,
                1 => *binding_type = TypeId::STRING,
                2 => *category = IterationBindingCategory::CopyValue,
                _ => unreachable!(),
            }
            assert!(verify_hir(&bad).is_err());
        }
    }
    #[test]
    fn string_hir_metadata_corruptions_are_rejected() {
        let mut invalid_utf8 = check("int main(){string s=\"ok\";return 0;}").unwrap();
        let HirStmtKind::Local { initializer, .. } =
            &mut invalid_utf8.functions[0].body.statements[0].kind
        else {
            panic!("expected string local");
        };
        let HirExprKind::String(op) = &mut initializer.kind else {
            panic!("expected string literal");
        };
        **op = crate::StringOp::Literal { bytes: vec![0xff] };
        assert!(verify_hir(&invalid_utf8).is_err());

        let mut wrong_result = check("int main(){string s=\"ok\";return 0;}").unwrap();
        let HirStmtKind::Local { initializer, .. } =
            &mut wrong_result.functions[0].body.statements[0].kind
        else {
            panic!("expected string local");
        };
        initializer.ty = TypeId::BOOL;
        assert!(verify_hir(&wrong_result).is_err());
    }
    #[test]
    fn core_hir_identity_corruption_is_rejected() {
        let mut hir = check("int main(){double x=exp(1.0);return 0;}").unwrap();
        let HirStmtKind::Local { initializer, .. } = &mut hir.functions[0].body.statements[0].kind
        else {
            panic!("expected Core local");
        };
        let HirExprKind::Core(call) = &mut initializer.kind else {
            panic!("expected Core call");
        };
        call.function.identity.profile = 99;
        assert!(verify_hir(&hir).is_err());
    }
    #[test]
    fn composed_string_hir_cleanup_corruption_is_rejected() {
        let mut hir =
            check("struct S{string value;}int main(){S value=S(\"a\"+\"b\");return 0;}").unwrap();
        let HirStmtKind::Return { drops, .. } =
            &mut hir.functions[0].body.statements.last_mut().unwrap().kind
        else {
            panic!("expected return");
        };
        drops.push(drops[0]);
        assert!(verify_hir(&hir).is_err());
    }
    #[test]
    fn verifier_rejects_duplicate_finally_identity() {
        let mut hir =
            check("int main(){try{try{}finally{int x=1;}}finally{int y=2;}return 0;}").unwrap();
        let HirStmtKind::Try {
            body,
            finally: Some(outer),
            ..
        } = &mut hir.functions[0].body.statements[0].kind
        else {
            panic!("expected outer finally");
        };
        let HirStmtKind::Try {
            finally: Some(inner),
            ..
        } = &body.statements[0].kind
        else {
            panic!("expected inner finally");
        };
        outer.id = inner.id;
        assert!(verify_hir(&hir).is_err());
    }
    #[test]
    fn scalar_aliases() {
        let h=check("alias Small=int8;int64 widen(Small x){return x;}int main(){Small x=-128;uint8 y=255;float32 f=1.5;float64 g=f+2.0;return widen(x);}").unwrap();
        assert_eq!(h.aliases()[0].canonical, TypeId::INT8);
    }
    #[test]
    fn type_ids_canonicalize_aliases_and_preserve_nominality_everywhere() {
        let h = check(
            "struct A{int x;}struct B{int x;}enum E{V(int)}enum F{V(int)}alias Whole=int64;alias Again=Whole;alias Position=A;int64 cast(Whole x){return int64(x);}int main(){Position p=Position(1);E e=E.V(p.x);return cast(p.x);}",
        )
        .unwrap();
        let types = h.types();
        assert_eq!(
            h.aliases
                .iter()
                .find(|a| a.name == "Whole")
                .unwrap()
                .canonical,
            TypeId::INT64
        );
        assert_eq!(
            h.aliases
                .iter()
                .find(|a| a.name == "Again")
                .unwrap()
                .canonical,
            TypeId::INT64
        );
        let a = types.id_of(TypeData::Struct(StructId(0))).unwrap();
        let b = types.id_of(TypeData::Struct(StructId(1))).unwrap();
        let e = types.id_of(TypeData::Enum(EnumId(0))).unwrap();
        let f = types.id_of(TypeData::Enum(EnumId(1))).unwrap();
        assert_ne!(a, b);
        assert_ne!(e, f);
        assert_eq!(
            h.aliases
                .iter()
                .find(|alias| alias.name == "Position")
                .unwrap()
                .canonical,
            a
        );
        assert_eq!(h.structs[0].fields[0].ty, TypeId::INT64);
        assert_eq!(h.enums[0].variants[0].payloads[0].ty, TypeId::INT64);
        assert_eq!(h.signatures[0].parameters[0].ty, TypeId::INT64);
        assert_eq!(h.signatures[0].return_type, TypeId::INT64);
        assert!(h.dump().contains("source_type: TypeId"));
    }

    #[test]
    fn verifier_rejects_an_invalid_type_id() {
        let mut h = check("int main(){return 0;}").unwrap();
        h.functions[0].locals.push(HirLocal {
            id: LocalId(0),
            name: "corrupt".into(),
            ty: TypeId(u32::MAX),
            span: Span::new(0, 0),
            parameter: false,
            source_binding: false,
            mutability: crate::BindingMutability::Mutable,
            address_taken: false,
        });
        assert!(verify_hir(&h).is_err());
    }

    #[test]
    fn verifier_rejects_generic_declaration_type_as_a_value_type() {
        let mut h = check(
            "struct Box<T>{T value;}int main(){Box<int> value=Box<int>(1);return value.value;}",
        )
        .unwrap();
        let raw = h.types.id_of(TypeData::Struct(StructId(0))).unwrap();
        let main = h
            .functions
            .iter_mut()
            .find(|function| h.instances[function.id.0 as usize].name == "main")
            .unwrap();
        main.locals[0].ty = raw;
        let errors = verify_hir(&h).unwrap_err();
        assert!(errors[0].message.contains("incomplete generic application"));
    }

    #[test]
    fn verifier_rejects_duplicate_const_initialization() {
        let mut hir = check("int main(){const int x=1;return x-1;}").unwrap();
        let duplicate = hir.functions[0].body.statements[0].clone();
        hir.functions[0].body.statements.insert(1, duplicate);
        assert!(verify_hir(&hir).is_err());
    }
    #[test]
    fn layout_boundary_uses_target_properties_and_cached_aggregates() {
        let h =
            check("struct Pair{int8 a;int64 b;}enum E{A, B(Pair)}int main(){return 0;}").unwrap();
        assert_eq!(
            layout_of(
                h.types(),
                TypeId::ISIZE,
                TargetProperties { pointer_width: 32 },
                h.structs(),
                h.enums(),
            ),
            Some(TypeLayout { size: 4, align: 4 })
        );
        let pair = h.types().id_of(TypeData::Struct(StructId(0))).unwrap();
        assert_eq!(
            layout_of(
                h.types(),
                pair,
                TargetProperties::LINUX_X86_64,
                h.structs(),
                h.enums(),
            ),
            Some(TypeLayout { size: 16, align: 8 })
        );
    }
    #[test]
    fn failures() {
        assert_eq!(
            check("alias A=B;alias B=A;int main(){return 0;}").unwrap_err()[0].code,
            "E0226"
        );
        assert_eq!(
            check("int main(){int8 x=128;return x;}").unwrap_err()[0].code,
            "E0209"
        );
    }
    #[test]
    fn recursion() {
        check("int fact(int n){if(n<=1){return 1;}return n*fact(n-1);}int main(){return fact(5);}")
            .unwrap();
    }
    #[test]
    fn explicit_scalar_casts_are_typed_and_constant_checked() {
        let hir = check("alias Tiny=int8;int main(){int64 x=127;Tiny y=Tiny(x);uint16 u=uint16(y);float64 f=double(u);return int32(f);}").unwrap();
        let dump = hir.dump();
        assert!(dump.contains("ExplicitCast"));
        assert!(dump.contains("source_type"));
        assert!(dump.contains("target_type"));
        check("int main(){uint64 x=uint64(18446744073709551615);return 0;}").unwrap();
        check("int main(){return int8(-128.9);}").unwrap();

        for (source, code) in [
            ("int main(){return int8(128);}", "E0231"),
            ("int main(){return uint32(-1);}", "E0231"),
            ("int main(){return int8(-129.0);}", "E0231"),
            ("int main(){return int(true);}", "E0232"),
            ("int main(){return bool(1);}", "E0232"),
            ("int main(){return int32(1.0,2.0);}", "E0230"),
        ] {
            assert_eq!(check(source).unwrap_err()[0].code, code, "{source}");
        }
    }
    #[test]
    fn division_and_remainder_constants_follow_v1_rules() {
        check("int main(){if(-5/2==-2){if(-5%2==-1){return 42;}}return 0;}").unwrap();
        check("int main(){int8 a=7;int16 b=2;return a/b;}").unwrap();
        check("int main(){float32 a=5.0;float64 b=2.0;float64 c=a/b;return int(c);}").unwrap();
        for (source, code) in [
            ("int main(){return 1/0;}", "E0233"),
            ("int main(){return -9223372036854775808/-1;}", "E0234"),
            ("int main(){return int(4.0%2.0);}", "E0235"),
        ] {
            assert_eq!(check(source).unwrap_err()[0].code, code, "{source}");
        }
        check("int main(){return -9223372036854775808%-1;}").unwrap();
    }

    #[test]
    fn nominal_structs_resolve_and_hir_verifies_field_identity() {
        let hir =
            check("struct P{int x;float64 y;}alias A=P;int main(){A p=A(1,2.0);p.x=3;return p.x;}")
                .unwrap();
        assert_eq!(hir.structs[0].layout, TypeLayout { size: 16, align: 8 });
        assert!(hir.dump().contains("StructInit"));

        let mut corrupt = hir;
        let initializer = corrupt.functions[0]
            .body
            .statements
            .iter_mut()
            .find_map(|statement| match &mut statement.kind {
                HirStmtKind::Local { initializer, .. } => Some(initializer),
                _ => None,
            })
            .unwrap();
        if let HirExprKind::StructInit { fields, .. } = &mut initializer.kind {
            fields[0].0 = FieldId(999);
        }
        assert!(verify_hir(&corrupt).is_err());
    }
    #[test]
    fn vertical26_hir_rejects_shared_projection_source() {
        for (operation, orientation) in [("row_mut", "Row"), ("column_mut", "Column")] {
            let mut h = check(&format!("int main(){{Matrix<int> a=[1];MatrixView<int> shared=matrix_view(a);VectorViewMut<int,{orientation}> w={operation}(a,1);return w[1];}}")).unwrap();
            let shared = h.functions[0]
                .locals
                .iter()
                .find(|l| l.name == "shared")
                .unwrap()
                .clone();
            let mut changed = false;
            for statement in &mut h.functions[0].body.statements {
                if let HirStmtKind::Local { initializer, .. } = &mut statement.kind
                    && let HirExprKind::MatrixAxisVectorView { source, .. } = &mut initializer.kind
                {
                    *source = HirPlace {
                        base: HirPlaceBase::Local(shared.id),
                        projections: vec![],
                        ty: shared.ty,
                    };
                    changed = true;
                }
            }
            assert!(changed);
            let errors = verify_hir(&h).unwrap_err();
            assert!(
                errors
                    .iter()
                    .any(|e| e.message.contains("capability contract")),
                "{errors:?}"
            );
        }
    }

    #[test]
    fn vertical26_hir_rejects_corrupt_projection_recipes() {
        use crate::types::{MatrixViewField, Orientation};
        for (operation, orientation) in [("row", "Row"), ("column", "Column")] {
            let hir = check(&format!("int main(){{Matrix<int> a=[1,2;3,4];VectorView<int,{orientation}> r={operation}(a,1);return r[1];}}")).unwrap();
            for case in 0..9 {
                if case < 9 {
                    let mut h = hir.clone();
                    let e = h.functions[0]
                        .body
                        .statements
                        .iter_mut()
                        .find_map(|s| match &mut s.kind {
                            HirStmtKind::Local { initializer, .. }
                                if matches!(
                                    initializer.kind,
                                    HirExprKind::MatrixAxisVectorView { .. }
                                ) =>
                            {
                                Some(initializer)
                            }
                            _ => None,
                        })
                        .unwrap();
                    let HirExprKind::MatrixAxisVectorView {
                        source,
                        fixed_index,
                        axis,
                        mutable,
                        descriptor,
                    } = &mut e.kind
                    else {
                        panic!()
                    };
                    match case {
                        0 => descriptor.fixed_extent = MatrixViewField::One,
                        1 => {
                            descriptor.base_stride = if *axis == Orientation::Row {
                                MatrixViewField::ColumnStride
                            } else {
                                MatrixViewField::RowStride
                            }
                        }
                        2 => descriptor.dimension = descriptor.fixed_extent,
                        3 => descriptor.stride = descriptor.base_stride,
                        4 => *axis = axis.transposed(),
                        5 => *mutable = true,
                        6 => fixed_index.ty = TypeId::INT64,
                        7 => source.ty = TypeId::INT64,
                        8 => {
                            e.kind = HirExprKind::View {
                                source: source.clone(),
                                mutable: false,
                            }
                        }
                        _ => unreachable!(),
                    }
                    assert!(verify_hir(&h).is_err(), "HIR accepted {operation} {case}");
                }
            }
        }
    }

    #[test]
    fn vertical25_hir_rejects_corrupt_vector_view_contracts() {
        let hir = check("int main(){Vector<int,Row> a=[1,2,3];VectorView<int,Column> v=transpose_view(a);return v[1];}").unwrap();
        for case in 0..6 {
            let mut corrupt = hir.clone();
            let initializer = corrupt.functions[0]
                .body
                .statements
                .iter_mut()
                .find_map(|s| {
                    if let HirStmtKind::Local { initializer, .. } = &mut s.kind
                        && matches!(initializer.kind, HirExprKind::VectorView { .. })
                    {
                        Some(initializer)
                    } else {
                        None
                    }
                })
                .unwrap();
            let HirExprKind::VectorView {
                source,
                mutable,
                transpose,
                descriptor,
            } = &mut initializer.kind
            else {
                panic!()
            };
            match case {
                0 => std::mem::swap(&mut descriptor.dimension, &mut descriptor.stride),
                1 => descriptor.stride = crate::types::VectorViewField::Dimension,
                2 => descriptor.dimension = crate::types::VectorViewField::One,
                3 => *mutable = true,
                4 => *transpose = false,
                5 => {
                    initializer.kind = HirExprKind::View {
                        source: source.clone(),
                        mutable: *mutable,
                    }
                }
                _ => unreachable!(),
            }
            assert!(
                verify_hir(&corrupt).is_err(),
                "accepted HIR corruption {case}"
            );
        }
    }

    #[test]
    fn vertical24_hir_rejects_corrupt_matrix_view_contracts() {
        let hir = check("int main(){Matrix<int> a=[1,2,3;4,5,6];MatrixView<int> v=transpose_view(a);return v[1,1];}").unwrap();
        for case in 0..6 {
            let mut corrupt = hir.clone();
            let initializer = corrupt.functions[0]
                .body
                .statements
                .iter_mut()
                .find_map(|s| {
                    if let HirStmtKind::Local { initializer, .. } = &mut s.kind
                        && matches!(initializer.kind, HirExprKind::MatrixView { .. })
                    {
                        Some(initializer)
                    } else {
                        None
                    }
                })
                .unwrap();
            let HirExprKind::MatrixView {
                source,
                mutable,
                transpose,
                descriptor,
            } = &mut initializer.kind
            else {
                panic!()
            };
            match case {
                0 => std::mem::swap(&mut descriptor.rows, &mut descriptor.columns),
                1 => descriptor.row_stride = crate::types::MatrixViewField::Rows,
                2 => descriptor.column_stride = crate::types::MatrixViewField::One,
                3 => *mutable = true,
                4 => *transpose = false,
                5 => {
                    initializer.kind = HirExprKind::View {
                        source: source.clone(),
                        mutable: *mutable,
                    }
                }
                _ => unreachable!(),
            }
            assert!(
                verify_hir(&corrupt).is_err(),
                "accepted HIR corruption {case}"
            );
        }
    }

    #[test]
    fn vertical22_hir_rejects_corrupt_transpose_contracts() {
        let hir = check(
            "int main(){Vector<int,Row> r=[1];Vector<int,Column> c=transpose(r);return c[1];}",
        )
        .unwrap();
        for case in 0..5 {
            let mut corrupt = hir.clone();
            let initializer = corrupt.functions[0]
                .body
                .statements
                .iter_mut()
                .find_map(|statement| {
                    if let HirStmtKind::Local { initializer, .. } = &mut statement.kind
                        && matches!(initializer.kind, HirExprKind::VectorTranspose { .. })
                    {
                        Some(initializer)
                    } else {
                        None
                    }
                })
                .unwrap();
            let HirExprKind::VectorTranspose {
                operand,
                source_type,
            } = &mut initializer.kind
            else {
                panic!()
            };
            match case {
                0 => initializer.ty = *source_type,
                1 => *source_type = TypeId::BOOL,
                2 => {
                    initializer.ty = corrupt
                        .types
                        .intern_vector(TypeId::FLOAT64, Orientation::Column)
                }
                3 => initializer.ty = TypeId::INT64,
                4 => {
                    let HirExprKind::Move(local) = operand.kind else {
                        panic!()
                    };
                    operand.kind = HirExprKind::Local(local);
                }
                _ => unreachable!(),
            }
            let errors = verify_hir(&corrupt).unwrap_err();
            assert!(errors[0].message.contains("Vector transpose"), "{errors:?}");
        }
    }

    #[test]
    fn vertical23_hir_rejects_corrupt_matrix_contracts() {
        let hir=check("int main(){Matrix<int> a=[1,2,3;4,5,6];usize n=rows(a);usize m=columns(a);int x=a[2,3];return x+int(n+m);}").unwrap();
        for case in 0..8 {
            let mut corrupt = hir.clone();
            let mut changed = false;
            for stmt in &mut corrupt.functions[0].body.statements {
                if let HirStmtKind::Local { initializer, .. } = &mut stmt.kind {
                    match (&mut initializer.kind, case) {
                        (HirExprKind::MatrixInit { rows, columns, .. }, 0) => {
                            std::mem::swap(rows, columns);
                            changed = true;
                        }
                        (HirExprKind::MatrixInit { element_type, .. }, 1) => {
                            *element_type = TypeId::BOOL;
                            changed = true;
                        }
                        (HirExprKind::MatrixInit { row_ends, .. }, 2) => {
                            row_ends[0] += 1;
                            changed = true;
                        }
                        (
                            HirExprKind::MatrixInit {
                                element_type,
                                elements,
                                ..
                            },
                            3,
                        ) => {
                            initializer.kind = HirExprKind::VectorInit {
                                element_type: *element_type,
                                elements: elements.clone(),
                            };
                            changed = true;
                        }
                        (HirExprKind::MatrixRows { source }, 4) => {
                            initializer.kind = HirExprKind::VectorDimension {
                                source: source.clone(),
                            };
                            changed = true;
                        }
                        (HirExprKind::Load(place), 5..=7) => {
                            for projection in &mut place.projections {
                                if let HirPlaceProjection::Index {
                                    column,
                                    semantics,
                                    checked,
                                    ..
                                } = projection
                                {
                                    match case {
                                        5 => *column = None,
                                        6 => *semantics = IndexSemantics::OneBased,
                                        _ => *checked = false,
                                    }
                                    changed = true;
                                }
                            }
                        }
                        _ => {}
                    }
                }
            }
            assert!(changed, "HIR {case}");
            assert!(verify_hir(&corrupt).is_err(), "HIR {case}");
        }
    }

    #[test]
    fn vertical21_hir_rejects_erased_vector_contracts() {
        let hir = check("int main(){Vector<int,Row> v=[10,20];usize n=dimension(v);int x=v[1];return x+int(n);}").unwrap();
        for case in 0..3 {
            let mut corrupt = hir.clone();
            let mut changed = false;
            for statement in &mut corrupt.functions[0].body.statements {
                if let HirStmtKind::Local { initializer, .. } = &mut statement.kind {
                    match (&mut initializer.kind, case) {
                        (
                            HirExprKind::VectorInit {
                                element_type,
                                elements,
                            },
                            0,
                        ) => {
                            initializer.kind = HirExprKind::ArrayInit {
                                element_type: *element_type,
                                elements: elements.clone(),
                            };
                            changed = true;
                        }
                        (HirExprKind::VectorDimension { source }, 1) => {
                            initializer.kind = HirExprKind::ArrayLength {
                                source: source.clone(),
                            };
                            changed = true;
                        }
                        (HirExprKind::Load(place), 2) => {
                            for projection in &mut place.projections {
                                if let HirPlaceProjection::Index { semantics, .. } = projection {
                                    *semantics = IndexSemantics::ZeroBased;
                                    changed = true;
                                }
                            }
                        }
                        _ => {}
                    }
                }
            }
            assert!(changed, "HIR case {case}");
            assert!(verify_hir(&corrupt).is_err(), "HIR case {case}");
        }
    }
    #[test]
    fn vertical27_hir_rejects_corrupt_math_types_and_ops() {
        for matrix in [false, true] {
            let ty = if matrix {
                "Matrix<int>"
            } else {
                "Vector<int,Row>"
            };
            let h = check(&format!("int main(){{{ty} a=[1,2];{ty} b=a+a;return 0;}}")).unwrap();
            for case in 0..6 {
                let mut bad = h.clone();
                let owner_ty = bad.functions[0].locals[0].ty;
                let initializer = bad.functions[0]
                    .body
                    .statements
                    .iter_mut()
                    .find_map(|s| {
                        if let HirStmtKind::Local { initializer, .. } = &mut s.kind {
                            if matches!(
                                initializer.kind,
                                HirExprKind::VectorElementwiseBinary { .. }
                                    | HirExprKind::MatrixElementwiseBinary { .. }
                            ) {
                                return Some(initializer);
                            }
                        }
                        None
                    })
                    .unwrap();
                if case == 0 {
                    initializer.ty = TypeId::BOOL;
                } else if case == 5 {
                    let (HirExprKind::VectorElementwiseBinary { shape_check, .. }
                    | HirExprKind::MatrixElementwiseBinary { shape_check, .. }) =
                        &mut initializer.kind
                    else {
                        unreachable!()
                    };
                    *shape_check = if matrix {
                        MathShapeCheck::VectorDimension
                    } else {
                        MathShapeCheck::MatrixRowsThenColumns
                    };
                } else {
                    let (HirExprKind::VectorElementwiseBinary {
                        op,
                        element_type: element,
                        left,
                        ..
                    }
                    | HirExprKind::MatrixElementwiseBinary {
                        op,
                        element_type: element,
                        left,
                        ..
                    }) = &mut initializer.kind
                    else {
                        unreachable!()
                    };
                    match case {
                        1 => *op = MathElementOp::Concrete(HirBinaryOp::MultiplyIntegerChecked),
                        2 => *element = TypeId::BOOL,
                        3 => left.ty = TypeId::INT64,
                        4 => {
                            left.ty = owner_ty;
                            left.kind = HirExprKind::Local(LocalId(0));
                        }
                        _ => unreachable!(),
                    }
                }
                assert!(verify_hir(&bad).is_err(), "{matrix} {case}");
            }
        }
    }
    #[test]
    fn vertical28_hir_rejects_scalar_side_type_and_consumption() {
        for matrix in [false, true] {
            for scalar_left in [false, true] {
                let ty = if matrix {
                    "Matrix<int>"
                } else {
                    "Vector<int,Row>"
                };
                let expr = if scalar_left { "2*a" } else { "a*2" };
                let hir = check(&format!(
                    "int main(){{{ty}a=[1,2];{ty}b={expr};Vector<int,Column>other=[1];return 0;}}"
                ))
                .unwrap();
                for case in 0..6 {
                    let mut h = hir.clone();
                    let owner_ty = h.functions[0].locals[0].ty;
                    let wrong_result = h.functions[0]
                        .locals
                        .iter()
                        .find(|l| l.name == "other")
                        .unwrap()
                        .ty;
                    let initializer = h.functions[0]
                        .body
                        .statements
                        .iter_mut()
                        .find_map(|s| {
                            if let HirStmtKind::Local { initializer, .. } = &mut s.kind {
                                if matches!(
                                    initializer.kind,
                                    HirExprKind::VectorScalarMultiply { .. }
                                        | HirExprKind::MatrixScalarMultiply { .. }
                                ) {
                                    return Some(initializer);
                                }
                            }
                            None
                        })
                        .unwrap();
                    let (HirExprKind::VectorScalarMultiply {
                        left,
                        right,
                        scalar_side,
                        element_type,
                        ..
                    }
                    | HirExprKind::MatrixScalarMultiply {
                        left,
                        right,
                        scalar_side,
                        element_type,
                        ..
                    }) = &mut initializer.kind
                    else {
                        unreachable!()
                    };
                    match case {
                        0 => {
                            *scalar_side = if *scalar_side == ScalarSide::Left {
                                ScalarSide::Right
                            } else {
                                ScalarSide::Left
                            }
                        }
                        1 => *element_type = TypeId::FLOAT64,
                        2 => initializer.ty = TypeId::BOOL,
                        3 => {
                            let source = if scalar_left { right } else { left };
                            source.ty = owner_ty;
                            source.kind = HirExprKind::Move(LocalId(0));
                        }
                        5 => initializer.ty = wrong_result,
                        _ => {
                            let scalar = if scalar_left { left } else { right };
                            scalar.ty = TypeId::INT8;
                        }
                    }
                    assert!(verify_hir(&h).is_err(), "HIR {matrix} {scalar_left} {case}");
                }
            }
        }
    }
    #[test]
    fn vertical29_behavior_is_separate_from_structural_properties() {
        let h = check("struct Point{double x;double y;}struct Holder<T:Add>{T value;}enum E<T:Mul>{Some(T)}T unused<T:Add+Sub+Mul>(T a,T b,T c,T d){return (a+b)*c-d;}int main(){Holder<int> h=Holder<int>(1);E<int> e=E<int>.Some(1);Buffer<int> b=Buffer<int>(0,0);Array<int> a={};List<int> l={};Vector<int,Row> v=[];Matrix<int> m=[];ref int r=&h.value;return 0;}").unwrap();
        let types = &h.types;
        for (ty, data) in types.entries() {
            for behavior in BehavioralCapability::ALL {
                let numeric = matches!(data, TypeData::Integer(_) | TypeData::Float(_));
                assert_eq!(types.satisfies_behavior(ty, behavior), numeric, "{data:?}");
                if !matches!(data, TypeData::GenericParam(_)) {
                    assert_eq!(types.guarantees_behavior(ty, behavior), numeric, "{data:?}");
                }
            }
        }
        let mut arena = TypeArena::default();
        let parameter = GenericParamId {
            owner: GenericOwner::Function(0),
            index: 0,
        };
        let ty = arena.intern(TypeData::GenericParam(parameter));
        let properties = arena.properties(ty);
        arena.register_generic_capabilities(
            parameter,
            "T".into(),
            BehavioralCapability::ALL.map(Capability::Behavioral),
        );
        assert_eq!(arena.properties(ty), properties);
        assert!(!arena.is_numeric(ty));
        assert!(!arena.guarantees_copy(ty));
        assert!(!arena.guarantees_relocatable(ty));
        assert!(!arena.guarantees_storable(ty));
        let all = [
            Capability::Copy,
            Capability::Relocatable,
            Capability::Storable,
        ]
        .into_iter()
        .chain(BehavioralCapability::ALL.map(Capability::Behavioral))
        .chain([Capability::Algebraic(AlgebraicCapability::Zero)])
        .collect::<Vec<_>>();
        for from in &all {
            for to in &all {
                assert_eq!(
                    from.implies(*to),
                    from == to || (*from == Capability::Copy && *to == Capability::Relocatable)
                );
            }
        }
    }

    #[test]
    fn vertical29_hir_rejects_corrupt_parametric_and_concrete_operations() {
        let h = check("T add<T:Add>(T a,T b){return a+b;}int main(){return add(20,22);}").unwrap();
        for case in 0..8 {
            let mut bad = h.clone();
            let HirStmtKind::Return { value, .. } =
                &mut bad.generic_functions[0].body.statements[0].kind
            else {
                panic!()
            };
            let HirExprKind::CapabilityBinary {
                behavior,
                left,
                right,
            } = &mut value.kind
            else {
                panic!()
            };
            match case {
                0 => *behavior = BehavioralCapability::Sub,
                1 => *behavior = BehavioralCapability::Mul,
                2 => value.ty = TypeId::BOOL,
                3 => left.ty = TypeId::INT64,
                4 => right.ty = TypeId::FLOAT64,
                5 => {
                    value.kind = HirExprKind::Binary {
                        op: HirBinaryOp::AddIntegerChecked,
                        left: left.clone(),
                        right: right.clone(),
                    }
                }
                6 => bad.signatures[0].generic_parameters[0].capabilities.clear(),
                7 => {
                    let id = bad.signatures[0].generic_parameters[0].id;
                    bad.types.register_generic_capabilities(id, "T".into(), []);
                }
                _ => unreachable!(),
            }
            let errors = verify_hir(&bad).unwrap_err();
            assert_eq!(errors[0].code, "E0348", "case {case}");
        }
        // A correct concrete-capability node is legal only in parametric HIR;
        // the post-monomorphization border insists on reified scalar operations.
        let mut bad = check("int main(){int a=20;int b=22;return a+b;}").unwrap();
        let HirStmtKind::Return { value, .. } = &mut bad.functions[0].body.statements[2].kind
        else {
            panic!()
        };
        let HirExprKind::Binary { left, right, .. } = &value.kind else {
            panic!()
        };
        value.kind = HirExprKind::CapabilityBinary {
            behavior: BehavioralCapability::Add,
            left: left.clone(),
            right: right.clone(),
        };
        assert!(
            verify_hir(&bad).unwrap_err()[0]
                .message
                .contains("unresolved CapabilityBinary")
        );
        // Concrete bool cannot acquire behavior, even in the parametric tree.
        let mut bad = check("bool eq(bool a,bool b){return a==b;}int main(){return 0;}").unwrap();
        let HirStmtKind::Return { value, .. } =
            &mut bad.generic_functions[0].body.statements[0].kind
        else {
            panic!()
        };
        let HirExprKind::Binary { left, right, .. } = &value.kind else {
            panic!()
        };
        value.kind = HirExprKind::CapabilityBinary {
            behavior: BehavioralCapability::Add,
            left: left.clone(),
            right: right.clone(),
        };
        assert!(verify_hir(&bad).is_err());
    }

    #[test]
    fn vertical29_invalid_requirements_never_allocate_or_cache_instance_ids() {
        for cap in ["Add", "Sub", "Mul", "Zero"] {
            let h = check(&format!(
                "T keep<T:{cap}>(T a){{return a;}}int main(){{return 0;}}"
            ))
            .unwrap();
            let mut types = h.types.clone();
            let buffer = types.intern_buffer(TypeId::INT64);
            let mut mono = Monomorphizer {
                types: &mut types,
                signatures: &h.signatures,
                declarations: &h.generic_functions,
                structs: &h.structs,
                enums: &h.enums,
                ids: BTreeMap::new(),
                queue: vec![],
                parents: vec![],
                current: None,
                instances: vec![],
                functions: vec![],
            };
            for argument in [TypeId::BOOL, buffer, TypeId::BOOL] {
                let errors = mono
                    .request(
                        InstanceKey {
                            function: FunctionId(0),
                            arguments: vec![argument],
                        },
                        h.signatures[0].span,
                    )
                    .unwrap_err();
                assert_eq!(errors[0].code, "E0316");
                assert!(errors[0].message.contains(cap));
                assert!(mono.ids.is_empty() && mono.queue.is_empty() && mono.parents.is_empty());
                assert!(mono.instances.is_empty() && mono.functions.is_empty());
            }
            let valid = InstanceKey {
                function: FunctionId(0),
                arguments: vec![TypeId::INT64],
            };
            assert_eq!(
                mono.request(valid.clone(), h.signatures[0].span).unwrap(),
                crate::InstanceId(0)
            );
            assert_eq!(
                mono.request(valid, h.signatures[0].span).unwrap(),
                crate::InstanceId(0)
            );
            assert!(
                mono.request(
                    InstanceKey {
                        function: FunctionId(0),
                        arguments: vec![buffer]
                    },
                    h.signatures[0].span
                )
                .is_err()
            );
            assert_eq!(mono.ids.len(), 1);
            assert_eq!(mono.queue.len(), 1);
            assert_eq!(mono.parents.len(), 1);
        }
    }

    #[test]
    fn vertical29_forwarding_metadata_is_independently_verified() {
        let mut h = check("T inner<T:Add>(T a,T b){return a+b;}T outer<T:Add>(T a,T b){return inner(a,b);}int main(){return 0;}").unwrap();
        // Corrupt callee constraints consistently in both declaration and arena;
        // the operator itself is still valid, but forwarding must now fail.
        let parameter = &mut h.signatures[0].generic_parameters[0];
        parameter
            .capabilities
            .insert(Capability::Behavioral(BehavioralCapability::Mul));
        h.types.register_generic_capabilities(
            parameter.id,
            parameter.name.clone(),
            parameter.capabilities.iter().copied(),
        );
        let errors = verify_hir(&h).unwrap_err();
        assert!(
            errors[0]
                .message
                .contains("call missing required capability")
        );
    }
    #[test]
    fn vertical30_hir_independently_verifies_symbolic_kernel_contracts() {
        for matrix in [false, true] {
            for scaling in [false, true] {
                let owner = if matrix { "Matrix<T>" } else { "Vector<T,Row>" };
                let (param, expr) = if scaling {
                    ("T b".to_owned(), "*a*b")
                } else {
                    (format!("ref {owner} b"), "*a+*b")
                };
                // All behaviors are present: replacing Add with Mul or Sub must
                // still disagree with the retained source operator.
                let h = check(&format!("{owner} kernel<T:Storable+Copy+Add+Sub+Mul>(ref {owner} a,{param}){{return {expr};}}int main(){{return 0;}}")).unwrap();
                for case in 0..9 {
                    let mut bad = h.clone();
                    if case == 2 || case == 3 {
                        let cap = if case == 2 {
                            Capability::Copy
                        } else {
                            Capability::Storable
                        };
                        let p = &mut bad.signatures[0].generic_parameters[0];
                        p.capabilities.remove(&cap);
                        bad.types.register_generic_capabilities(
                            p.id,
                            p.name.clone(),
                            p.capabilities.iter().copied(),
                        );
                    } else {
                        let HirStmtKind::Return { value, .. } =
                            &mut bad.generic_functions[0].body.statements[0].kind
                        else {
                            panic!()
                        };
                        let (HirExprKind::VectorElementwiseBinary {
                            op,
                            element_type,
                            left,
                            ..
                        }
                        | HirExprKind::MatrixElementwiseBinary {
                            op,
                            element_type,
                            left,
                            ..
                        }
                        | HirExprKind::VectorScalarMultiply {
                            op,
                            element_type,
                            left,
                            ..
                        }
                        | HirExprKind::MatrixScalarMultiply {
                            op,
                            element_type,
                            left,
                            ..
                        }) = &mut value.kind
                        else {
                            panic!()
                        };
                        match case {
                            0 => {
                                *op = MathElementOp::Behavioral(if scaling {
                                    BehavioralCapability::Add
                                } else {
                                    BehavioralCapability::Mul
                                })
                            }
                            1 => *op = MathElementOp::Behavioral(BehavioralCapability::Sub),
                            4 => value.ty = TypeId::BOOL,
                            5 => *element_type = TypeId::INT64,
                            6 => *op = MathElementOp::Concrete(HirBinaryOp::AddIntegerChecked),
                            7 => left.ty = TypeId::BOOL,
                            8 => {
                                let t = *element_type;
                                value.ty = if matrix {
                                    bad.types.intern_vector(t, crate::Orientation::Row)
                                } else {
                                    bad.types.intern_vector(t, crate::Orientation::Column)
                                };
                            }
                            _ => unreachable!(),
                        }
                    }
                    let e = verify_hir(&bad).unwrap_err();
                    assert_eq!(e[0].code, "E0348", "{matrix} {scaling} {case}: {e:?}");
                    if case == 2 || case == 3 {
                        assert!(
                            e[0].message
                                .contains(if case == 2 { "Copy" } else { "Storable" }),
                            "{e:?}"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn vertical30_concrete_hir_rejects_residual_behavioral_kernel() {
        for matrix in [false, true] {
            for (cap, expr) in [
                (BehavioralCapability::Add, "a+a"),
                (BehavioralCapability::Sub, "a-a"),
                (BehavioralCapability::Mul, "2*a"),
            ] {
                let ty = if matrix {
                    "Matrix<int>"
                } else {
                    "Vector<int,Row>"
                };
                let mut h =
                    check(&format!("int main(){{{ty}a=[1,2];{ty}b={expr};return 0;}}")).unwrap();
                let HirStmtKind::Local { initializer, .. } =
                    &mut h.functions[0].body.statements[1].kind
                else {
                    panic!()
                };
                let (HirExprKind::VectorElementwiseBinary { op, .. }
                | HirExprKind::MatrixElementwiseBinary { op, .. }
                | HirExprKind::VectorScalarMultiply { op, .. }
                | HirExprKind::MatrixScalarMultiply { op, .. }) = &mut initializer.kind
                else {
                    panic!()
                };
                *op = MathElementOp::Behavioral(cap);
                let e = verify_hir(&h).unwrap_err();
                assert_eq!(e[0].code, "E0290");
                assert!(
                    e[0].message
                        .contains("unresolved behavioral mathematical kernel")
                );
            }
        }
    }
    #[test]
    fn vertical31_zero_taxonomy_satisfaction_and_no_implications() {
        let zero = Capability::Algebraic(AlgebraicCapability::Zero);
        let h=check("struct S{int value;}enum E{A(int)}T keep<T:Zero>(T a){return a;}int main(){Vector<int,Row>v=[];Matrix<int>m=[];Array<int>a={};List<int>l={};Buffer<int>b=Buffer<int>(0,0);VectorView<int,Row>w=vector_view(v);return 0;}").unwrap();
        for (id, data) in h.types.entries() {
            let expected = matches!(
                data,
                TypeData::Integer(_) | TypeData::Float(_) | TypeData::GenericParam(_)
            );
            assert_eq!(
                h.types.guarantees_capability(id, zero),
                expected,
                "{data:?}"
            );
        }
        let t = h.signatures[0].generic_parameters[0].ty;
        for cap in [
            Capability::Copy,
            Capability::Relocatable,
            Capability::Storable,
        ]
        .into_iter()
        .chain(BehavioralCapability::ALL.map(Capability::Behavioral))
        .chain([zero])
        {
            assert_eq!(zero.implies(cap), cap == zero);
            assert_eq!(cap.implies(zero), cap == zero);
            assert_eq!(h.types.guarantees_capability(t, cap), cap == zero);
        }
        assert!(!h.types.is_numeric(t));
    }

    #[test]
    fn vertical31_hir_product_corruption_and_erased_guarantees() {
        for inner in [true, false] {
            let (result, lo, ro, caps) = if inner {
                ("T", "Row", "Column", "Copy+Add+Mul+Zero")
            } else {
                ("Matrix<T>", "Column", "Row", "Storable+Copy+Mul")
            };
            let h=check(&format!("{result} product<T:{caps}>(VectorView<T,{lo}>a,VectorView<T,{ro}>b){{return a*b;}}int main(){{return 0;}}")).unwrap();
            for case in 0..10 {
                let mut bad = h.clone();
                let t = bad.signatures[0].generic_parameters[0].ty;
                let row = bad
                    .types
                    .intern_vector_view(t, crate::Orientation::Row, false);
                let col = bad
                    .types
                    .intern_vector_view(t, crate::Orientation::Column, false);
                let matrix = bad.types.intern_matrix(t);
                let HirStmtKind::Return { value, .. } =
                    &mut bad.generic_functions[0].body.statements[0].kind
                else {
                    panic!()
                };
                let HirExprKind::AlgebraicProduct {
                    left,
                    right,
                    element_type,
                    product_op,
                    product,
                } = &mut value.kind
                else {
                    panic!()
                };
                match case {
                    0 => {
                        left.ty = if inner { col } else { row };
                        right.ty = if inner { row } else { col };
                    }
                    1 => value.ty = if inner { matrix } else { t },
                    2 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Add),
                    3 => *element_type = TypeId::INT64,
                    4 => left.ty = bad.types.intern_matrix_view(t, false),
                    5..=9 => match product {
                        AlgebraicProductKind::MatrixVector { .. }
                        | AlgebraicProductKind::MatrixMatrix { .. } => unreachable!(),
                        AlgebraicProductKind::Inner {
                            shape_check,
                            accumulate_op,
                            zero,
                        } => match case {
                            5 => {
                                *accumulate_op =
                                    MathElementOp::Behavioral(BehavioralCapability::Mul)
                            }
                            6 => zero.ty = TypeId::INT64,
                            7 => zero.kind = HirExprKind::Int(0),
                            8 => *shape_check = MathShapeCheck::MatrixRowsThenColumns,
                            9 => {
                                *product = AlgebraicProductKind::Outer {
                                    rows: ScalarSide::Left,
                                    columns: ScalarSide::Right,
                                }
                            }
                            _ => unreachable!(),
                        },
                        AlgebraicProductKind::Outer { rows, columns } => match case {
                            5 => *rows = ScalarSide::Right,
                            6 => *columns = ScalarSide::Left,
                            7 => std::mem::swap(rows, columns),
                            8 => {
                                *product = AlgebraicProductKind::Inner {
                                    shape_check: MathShapeCheck::VectorDimension,
                                    accumulate_op: MathElementOp::Behavioral(
                                        BehavioralCapability::Add,
                                    ),
                                    zero: Box::new(HirExpr {
                                        kind: HirExprKind::AlgebraicValue {
                                            capability: AlgebraicCapability::Zero,
                                        },
                                        ty: t,
                                        span: value.span,
                                    }),
                                }
                            }
                            9 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Sub),
                            _ => unreachable!(),
                        },
                    },
                    _ => unreachable!(),
                }
                assert!(verify_hir(&bad).is_err(), "{inner} {case}");
            }
            let caps: Vec<_> = h.signatures[0].generic_parameters[0]
                .capabilities
                .iter()
                .copied()
                .collect();
            for erased in caps {
                let mut bad = h.clone();
                let parameter = &mut bad.signatures[0].generic_parameters[0];
                parameter.capabilities.remove(&erased);
                bad.types.register_generic_capabilities(
                    parameter.id,
                    parameter.name.clone(),
                    parameter.capabilities.iter().copied(),
                );
                assert!(verify_hir(&bad).is_err(), "{inner} {erased}");
            }
        }
    }

    #[test]
    fn vertical31_concrete_hir_zero_and_operation_corruption() {
        for scalar in ["int8", "uint64", "float32", "float64"] {
            let h=check(&format!("int main(){{Vector<{scalar},Row>r=[];Vector<{scalar},Column>c=[];{scalar} x=r*c;return 0;}}")).unwrap();
            for case in 0..6 {
                let mut bad = h.clone();
                let HirStmtKind::Local { initializer, .. } =
                    &mut bad.functions[0].body.statements[2].kind
                else {
                    panic!()
                };
                let HirExprKind::AlgebraicProduct {
                    product_op,
                    product:
                        AlgebraicProductKind::Inner {
                            accumulate_op,
                            zero,
                            ..
                        },
                    ..
                } = &mut initializer.kind
                else {
                    panic!()
                };
                match case {
                    0 => {
                        zero.kind = HirExprKind::AlgebraicValue {
                            capability: AlgebraicCapability::Zero,
                        }
                    }
                    1 => zero.ty = TypeId::BOOL,
                    2 => zero.kind = HirExprKind::Int(1),
                    3 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Mul),
                    4 => *accumulate_op = MathElementOp::Behavioral(BehavioralCapability::Add),
                    5 => zero.kind = HirExprKind::Float(FloatValue::Float64(1_u64 << 63)),
                    _ => unreachable!(),
                }
                assert!(verify_hir(&bad).is_err(), "{scalar} {case}");
            }
        }
    }

    #[test]
    fn exception_hir_rejects_event_and_ownership_corruption() {
        let hir = check(
            "class P:Exception{public init(){}}int main(){try{throw P();}catch(P e){throw;}}",
        )
        .unwrap();

        let mut bad_rethrow = hir.clone();
        let HirStmtKind::Try { catches, .. } =
            &mut bad_rethrow.functions[0].body.statements[0].kind
        else {
            panic!("expected try")
        };
        let HirStmtKind::Rethrow { catch, .. } = &mut catches[0].body.statements[0].kind else {
            panic!("expected rethrow")
        };
        *catch = CatchId(u32::MAX);
        assert!(verify_hir(&bad_rethrow).is_err());

        let mut bad_transfer = hir;
        let HirStmtKind::Try { body, .. } = &mut bad_transfer.functions[0].body.statements[0].kind
        else {
            panic!("expected try")
        };
        let HirStmtKind::Throw { transfer, .. } = &mut body.statements[0].kind else {
            panic!("expected throw")
        };
        *transfer = false;
        assert!(verify_hir(&bad_transfer).is_err());
    }
}

#[cfg(test)]
mod vertical32_tests {
    use super::*;
    use crate::{SourceFile, parse_source};
    #[test]
    #[allow(clippy::too_many_lines)]
    fn vertical32_hir_corruption_and_erased_guarantees() {
        use crate::Orientation;
        for column in [true, false] {
            let (o, expr) = if column {
                ("Column", "a*x")
            } else {
                ("Row", "x*a")
            };
            let source = format!(
                "Vector<T,{o}> product<T:Storable+Copy+Add+Mul+Zero>(MatrixView<T>a,VectorView<T,{o}>x){{return {expr};}}int main(){{return 0;}}"
            );
            let h = analyze(parse_source(&SourceFile::new("hir.ae", source)).unwrap()).unwrap();
            for case in 0..14 {
                let mut bad = h.clone();
                let t = bad.signatures[0].generic_parameters[0].ty;
                let wrong_result = bad.types.intern_vector(
                    t,
                    if column {
                        Orientation::Row
                    } else {
                        Orientation::Column
                    },
                );
                let wrong_source = bad.types.intern_matrix_view(t, false);
                let HirStmtKind::Return { value, .. } =
                    &mut bad.generic_functions[0].body.statements[0].kind
                else {
                    panic!()
                };
                let HirExprKind::AlgebraicProduct {
                    left,
                    right,
                    element_type,
                    product_op,
                    product,
                } = &mut value.kind
                else {
                    panic!()
                };
                let AlgebraicProductKind::MatrixVector {
                    matrix_side,
                    shape_check,
                    result_extent,
                    contraction_extent,
                    accumulate_op,
                    zero,
                } = product
                else {
                    panic!()
                };
                match case {
                    0 => value.ty = wrong_result,
                    1 => std::mem::swap(result_extent, contraction_extent),
                    2 => *result_extent = *contraction_extent,
                    3 => *contraction_extent = *result_extent,
                    4 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Add),
                    5 => *accumulate_op = MathElementOp::Behavioral(BehavioralCapability::Mul),
                    6 => zero.ty = TypeId::BOOL,
                    7 => zero.kind = HirExprKind::Int(0),
                    8 => *shape_check = MathShapeCheck::VectorDimension,
                    9 => {
                        if column {
                            right.ty = wrong_source;
                        } else {
                            left.ty = wrong_source;
                        }
                    }
                    10 => {
                        *matrix_side = if column {
                            crate::ScalarSide::Right
                        } else {
                            crate::ScalarSide::Left
                        }
                    }
                    11 => *element_type = TypeId::INT64,
                    12 => value.ty = t,
                    13 => {
                        *product = AlgebraicProductKind::Outer {
                            rows: crate::ScalarSide::Left,
                            columns: crate::ScalarSide::Right,
                        }
                    }
                    _ => unreachable!(),
                }
                assert!(verify_hir(&bad).is_err(), "{column} {case}");
            }
            let caps = h.signatures[0].generic_parameters[0].capabilities.clone();
            for erased in caps {
                let mut bad = h.clone();
                let parameter = &mut bad.signatures[0].generic_parameters[0];
                parameter.capabilities.remove(&erased);
                bad.types.register_generic_capabilities(
                    parameter.id,
                    parameter.name.clone(),
                    parameter.capabilities.iter().copied(),
                );
                assert!(verify_hir(&bad).is_err(), "{column} {erased}");
            }
            for scalar in ["int8", "uint64", "float32", "float64"] {
                let h=analyze(parse_source(&SourceFile::new("concrete.ae",format!("int main(){{Matrix<{scalar}>a=[1];Vector<{scalar},{o}>x=[1];Vector<{scalar},{o}>y={expr};return 0;}}"))).unwrap()).unwrap();
                for case in 0..6 {
                    let mut bad = h.clone();
                    let HirStmtKind::Local { initializer, .. } =
                        &mut bad.functions[0].body.statements[2].kind
                    else {
                        panic!()
                    };
                    let HirExprKind::AlgebraicProduct {
                        product_op,
                        product:
                            AlgebraicProductKind::MatrixVector {
                                zero,
                                accumulate_op,
                                ..
                            },
                        ..
                    } = &mut initializer.kind
                    else {
                        panic!()
                    };
                    match case {
                        0 => {
                            zero.kind = HirExprKind::AlgebraicValue {
                                capability: crate::AlgebraicCapability::Zero,
                            }
                        }
                        1 => zero.ty = TypeId::BOOL,
                        2 => zero.kind = HirExprKind::Int(1),
                        3 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Mul),
                        4 => *accumulate_op = MathElementOp::Behavioral(BehavioralCapability::Add),
                        5 => {
                            zero.kind = HirExprKind::Float(crate::FloatValue::Float64(1_u64 << 63))
                        }
                        _ => unreachable!(),
                    }
                    assert!(verify_hir(&bad).is_err(), "{column} {scalar} {case}");
                }
            }
        }
    }
}

#[cfg(test)]
mod vertical33_tests {
    use super::*;
    use crate::{Orientation, SourceFile, parse_source};

    #[test]
    #[allow(clippy::too_many_lines)]
    fn vertical33_hir_corruption_and_erased_guarantees() {
        let h = analyze(parse_source(&SourceFile::new("hir.ae", "Matrix<T> product<T:Storable+Copy+Add+Mul+Zero>(MatrixView<T>a,MatrixView<T>b){return a*b;}int main(){return 0;}")).unwrap()).unwrap();
        for case in 0..17 {
            let mut bad = h.clone();
            let t = bad.signatures[0].generic_parameters[0].ty;
            let vector = bad.types.intern_vector(t, Orientation::Row);
            let view = bad.types.intern_vector_view(t, Orientation::Column, false);
            let wrong_element = bad.types.intern_matrix(TypeId::INT64);
            let HirStmtKind::Return { value, .. } =
                &mut bad.generic_functions[0].body.statements[0].kind
            else {
                panic!()
            };
            let HirExprKind::AlgebraicProduct {
                left,
                right,
                element_type,
                product_op,
                product,
            } = &mut value.kind
            else {
                panic!()
            };
            let AlgebraicProductKind::MatrixMatrix {
                shape_check,
                output_rows,
                output_columns,
                contraction_extent,
                accumulate_op,
                zero,
            } = product
            else {
                panic!()
            };
            match case {
                0 => output_rows.1 = MatrixProductExtent::Columns,
                1 => output_columns.1 = MatrixProductExtent::Rows,
                2 => contraction_extent.1 = MatrixProductExtent::Rows,
                3 => value.ty = vector,
                4 => value.ty = wrong_element,
                5 => *shape_check = MathShapeCheck::MatrixRowsThenColumns,
                6 => left.ty = view,
                7 => right.ty = view,
                8 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Add),
                9 => *accumulate_op = MathElementOp::Behavioral(BehavioralCapability::Mul),
                10 => zero.kind = HirExprKind::Int(0),
                11 => zero.ty = TypeId::BOOL,
                12 => output_rows.0 = ScalarSide::Right,
                13 => output_columns.0 = ScalarSide::Left,
                14 => contraction_extent.0 = ScalarSide::Right,
                15 => *element_type = TypeId::INT64,
                16 => {
                    *product = AlgebraicProductKind::Outer {
                        rows: ScalarSide::Left,
                        columns: ScalarSide::Right,
                    }
                }
                _ => unreachable!(),
            }
            assert!(verify_hir(&bad).is_err(), "symbolic {case}");
        }
        for erased in h.signatures[0].generic_parameters[0].capabilities.clone() {
            let mut bad = h.clone();
            let p = &mut bad.signatures[0].generic_parameters[0];
            p.capabilities.remove(&erased);
            bad.types.register_generic_capabilities(
                p.id,
                p.name.clone(),
                p.capabilities.iter().copied(),
            );
            assert!(verify_hir(&bad).is_err(), "{erased}");
        }
        for scalar in ["int8", "uint64", "float32", "float64"] {
            let h=analyze(parse_source(&SourceFile::new("concrete.ae",format!("int main(){{Matrix<{scalar}>a=[1];Matrix<{scalar}>b=[1];Matrix<{scalar}>c=a*b;return 0;}}"))).unwrap()).unwrap();
            for case in 0..8 {
                let mut bad = h.clone();
                let owner_ty = bad.functions[0].locals[0].ty;
                let HirStmtKind::Local { initializer, .. } =
                    &mut bad.functions[0].body.statements[2].kind
                else {
                    panic!()
                };
                let HirExprKind::AlgebraicProduct {
                    left,
                    right,
                    product_op,
                    product:
                        AlgebraicProductKind::MatrixMatrix {
                            zero,
                            accumulate_op,
                            ..
                        },
                    ..
                } = &mut initializer.kind
                else {
                    panic!()
                };
                match case {
                    0 => {
                        zero.kind = HirExprKind::AlgebraicValue {
                            capability: AlgebraicCapability::Zero,
                        }
                    }
                    1 => zero.ty = TypeId::BOOL,
                    2 => zero.kind = HirExprKind::Int(1),
                    3 => *product_op = MathElementOp::Behavioral(BehavioralCapability::Mul),
                    4 => *accumulate_op = MathElementOp::Behavioral(BehavioralCapability::Add),
                    5 => {
                        zero.kind = HirExprKind::Float(if scalar == "float32" {
                            FloatValue::Float32(1_u32 << 31)
                        } else {
                            FloatValue::Float64(1_u64 << 63)
                        })
                    }
                    6 => {
                        left.kind = HirExprKind::Move(LocalId(0));
                        left.ty = owner_ty;
                    }
                    7 => {
                        right.kind = HirExprKind::Move(LocalId(1));
                        right.ty = owner_ty;
                    }
                    _ => unreachable!(),
                }
                assert!(verify_hir(&bad).is_err(), "{scalar} {case}");
            }
        }
    }

    #[test]
    fn enum_equality_hir_contract_fails_closed_when_corrupted() {
        fn equality(hir: &mut TypedHir) -> &mut HirExpr {
            hir.generic_functions
                .iter_mut()
                .flat_map(|function| &mut function.body.statements)
                .find_map(|statement| match &mut statement.kind {
                    HirStmtKind::Local { initializer, .. }
                        if matches!(initializer.kind, HirExprKind::Binary { .. }) =>
                    {
                        Some(initializer)
                    }
                    _ => None,
                })
                .unwrap()
        }

        let source = "enum Box<T>{Empty,Full}enum Payload{None,Some(int)}bool same<T>(Box<T>a,Box<T>b){bool result=a==b;return result;}int main(){return 0;}";
        let hir =
            analyze(parse_source(&SourceFile::new("enum-equality.ae", source)).unwrap()).unwrap();
        verify_hir(&hir).unwrap();

        let mut wrong_result = hir.clone();
        let enum_ty = wrong_result.generic_functions[0].locals[0].ty;
        equality(&mut wrong_result).ty = enum_ty;
        let error = verify_hir(&wrong_result).unwrap_err();
        assert_eq!(error[0].code, "E0348");

        let mut ordered = hir.clone();
        let HirExprKind::Binary { op, .. } = &mut equality(&mut ordered).kind else {
            unreachable!()
        };
        *op = HirBinaryOp::Less;
        let error = verify_hir(&ordered).unwrap_err();
        assert_eq!(error[0].code, "E0348");

        let mut nominal_mismatch = hir.clone();
        let other_enum = nominal_mismatch
            .types
            .entries()
            .find_map(|(ty, _)| {
                (nominal_mismatch.types.enum_id(ty) == Some(EnumId(1))).then_some(ty)
            })
            .unwrap();
        let HirExprKind::Binary { right, .. } = &mut equality(&mut nominal_mismatch).kind else {
            unreachable!()
        };
        right.ty = other_enum;
        assert_eq!(verify_hir(&nominal_mismatch).unwrap_err()[0].code, "E0348");

        let mut instance_mismatch = hir.clone();
        let other_instance = instance_mismatch
            .types
            .intern_enum_instance(EnumId(0), vec![TypeId::FLOAT64]);
        let HirExprKind::Binary { right, .. } = &mut equality(&mut instance_mismatch).kind else {
            unreachable!()
        };
        right.ty = other_instance;
        assert_eq!(verify_hir(&instance_mismatch).unwrap_err()[0].code, "E0348");

        let mut payload_bearing = hir;
        let payload = payload_bearing.enums[1].variants[1].payloads[0].clone();
        payload_bearing.enums[0].variants[0].payloads.push(payload);
        let error = verify_hir(&payload_bearing).unwrap_err();
        assert_eq!(error[0].code, "E0348");
    }
}
