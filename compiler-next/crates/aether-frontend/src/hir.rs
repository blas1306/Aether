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
use crate::{
    AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstMatchArm, AstMatchMode,
    AstStmtKind, AstType, AstUnaryOp, Capability, CollectionElementAdmission, Diagnostic,
    DiagnosticCategory, EnumId, FieldId, FloatType, GenericOwner, GenericParamId, IntegerType,
    ParsedAst, Phase, SourceId, Span, StructId, Substitution, TargetProperties, TypeArena,
    TypeData, TypeId, VariantId,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ModuleId(pub u32);
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedImport {
    pub name: String,
    pub module: ModuleId,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ModuleInfo {
    pub id: ModuleId,
    pub name: String,
    pub source: SourceId,
    pub source_name: String,
    pub imports: Vec<ResolvedImport>,
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
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParameterSignature {
    pub name: String,
    pub ty: TypeId,
    pub span: Span,
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
        TypeData::Integer(integer) => {
            let bytes = u64::from(integer.bits(target) / 8);
            TypeLayout {
                size: bytes,
                align: bytes,
            }
        }
        TypeData::Float(FloatType::Float32) => TypeLayout { size: 4, align: 4 },
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
        TypeData::Reference { .. } => TypeLayout {
            size: u64::from(target.pointer_width / 8),
            align: u64::from(target.pointer_width / 8),
        },
        TypeData::Buffer { .. } | TypeData::Array { .. } | TypeData::View { .. } => TypeLayout {
            size: u64::from(target.pointer_width / 4),
            align: u64::from(target.pointer_width / 8),
        },
        TypeData::List { .. } => TypeLayout {
            size: 3 * u64::from(target.pointer_width / 8),
            align: u64::from(target.pointer_width / 8),
        },
        TypeData::GenericParam(_) => return None,
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
        Some(TypeData::Buffer { element }) => {
            format!("Buffer<{}>", format_type(types, *element, structs, enums))
        }
        Some(TypeData::Array { element }) => {
            format!("Array<{}>", format_type(types, *element, structs, enums))
        }
        Some(TypeData::List { element }) => {
            format!("List<{}>", format_type(types, *element, structs, enums))
        }
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

#[derive(Clone, Debug)]
pub struct DeclaredProgram {
    types: TypeArena,
    program: ParsedProgram,
    signatures: Vec<FunctionSignature>,
    names: Vec<BTreeMap<String, FunctionId>>,
    imports: Vec<BTreeMap<String, ModuleId>>,
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
    /// Requires stable memory because this local, or one of its fields, is borrowed.
    pub address_taken: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HirParameter {
    pub local: LocalId,
    pub ty: TypeId,
    pub span: Span,
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
                let guarantees = [Capability::Copy, Capability::Relocatable]
                    .into_iter()
                    .filter(|capability| self.types.guarantees_capability(id, *capability))
                    .map(|capability| capability.to_string())
                    .collect::<Vec<_>>()
                    .join(" + ");
                format!(
                    "  {id:?} = {}; properties={:?}; guarantees={}",
                    format_type(&self.types, id, &self.structs, &self.enums),
                    self.types
                        .properties(id)
                        .expect("canonical type properties"),
                    if guarantees.is_empty() {
                        "none"
                    } else {
                        &guarantees
                    }
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
        for m in &self.modules {
            let f: Vec<_> = self.functions.iter().filter(|f| f.module == m.id).collect();
            write!(d, "\nmodule {:?} `{}` functions: {f:#?}", m.id, m.name).unwrap();
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
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GenericHirFunction {
    pub id: FunctionId,
    pub module: ModuleId,
    pub parameters: Vec<HirParameter>,
    pub locals: Vec<HirLocal>,
    pub body: HirBlock,
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
    If {
        condition: HirExpr,
        then_block: HirBlock,
        else_block: Option<HirBlock>,
    },
    While {
        condition: HirExpr,
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
}

/// Semantic marker for operations that may invalidate addresses into a
/// List's element storage, independently of its runtime spare capacity.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StructuralMutation {
    Push,
    Reserve,
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
        element_type: TypeId,
        checked: bool,
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
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FloatValue {
    Float32(u32),
    Float64(u64),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HirExprKind {
    Int(i128),
    Float(FloatValue),
    Bool(bool),
    Local(LocalId),
    /// Explicit consuming use of a move-only local.
    Move(LocalId),
    Load(HirPlace),
    Borrow {
        place: HirPlace,
        mutable: bool,
    },
    BufferInit {
        element_type: TypeId,
        length: Box<HirExpr>,
        initial: Box<HirExpr>,
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
    /// Bootstrap `length(array-place)` query, resolved below HIR.
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
    View {
        source: HirPlace,
        mutable: bool,
    },
    Call {
        callee: HirCallTarget,
        type_arguments: Vec<TypeId>,
        args: Vec<HirExpr>,
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

pub fn collect_signatures(ast: ParsedAst) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    let source = ast.functions.first().map_or(SourceId(0), |f| f.span.source);
    collect_program_signatures(ParsedProgram {
        modules: vec![ParsedModule {
            info: ModuleInfo {
                id: ModuleId(0),
                name: "main".into(),
                source,
                source_name: "<memory>".into(),
                imports: vec![],
            },
            ast,
        }],
        entry: ModuleId(0),
    })
}
pub fn collect_program_signatures(
    program: ParsedProgram,
) -> Result<DeclaredProgram, Vec<Diagnostic>> {
    validate_program(&program)?;
    let imports: Vec<BTreeMap<String, ModuleId>> = program
        .modules
        .iter()
        .map(|m| {
            m.info
                .imports
                .iter()
                .map(|i| (i.name.clone(), i.module))
                .collect()
        })
        .collect();
    let module_names: BTreeMap<String, ModuleId> = program
        .modules
        .iter()
        .map(|m| (m.info.name.clone(), m.info.id))
        .collect();

    // One fail-closed top-level namespace per module. This guarantees that a
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
            .chain(module.ast.enums().iter().map(|d| ("enum", &d.name, d.span)))
            .chain(
                module
                    .ast
                    .functions()
                    .iter()
                    .map(|d| ("function", &d.name, d.span)),
            )
        {
            let previous = declarations.insert(name.clone(), kind);
            if builtin(name).is_some() || intrinsic_type_arity(name).is_some() || previous.is_some()
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

    let mut enum_names = vec![BTreeMap::new(); program.modules.len()];
    let mut enum_decls = Vec::new();
    for module in &program.modules {
        for declaration in module.ast.enums() {
            let id = EnumId(enum_decls.len() as u32);
            enum_names[module.info.id.0 as usize].insert(declaration.name.clone(), id);
            enum_decls.push((id, module.info.id, declaration));
        }
    }
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
            TypeData::Array { element } => (*element, 1),
            TypeData::List { element } => (*element, 2),
            _ => return None,
        };
        let admitted = match kind {
            1 | 2 => {
                types.collection_element_admission(element) == CollectionElementAdmission::Admitted
            }
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
                    if kind == 1 { "Array" } else { "List" },
                    format_type(&types, element, &structs, &enums),
                    types.collection_element_admission(element),
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
        if let Some(field) = info
            .fields
            .iter()
            .find(|field| types.contains_reference(field.ty) || types.contains_view(field.ty))
        {
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
            .find(|payload| types.contains_reference(payload.ty) || types.contains_view(payload.ty))
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
    let mut signatures = vec![];
    let mut names = vec![BTreeMap::new(); program.modules.len()];
    for module in &program.modules {
        for f in module.ast.functions() {
            let id = FunctionId(signatures.len() as u32);
            names[module.info.id.0 as usize].insert(f.name.clone(), id);
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
            let parameters = f
                .parameters
                .iter()
                .map(|p| {
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
                        span: p.span,
                    })
                })
                .collect::<Result<Vec<_>, _>>()
                .map_err(|d| vec![src(d, module)])?;
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
            for parameter in &parameters {
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
    if main.return_type != TypeId::INT64 || !main.parameters.is_empty() {
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
    let ty = if a.target.module.is_none()
        && a.target.arguments.is_empty()
        && decl.contains_key(&a.target.name)
    {
        resolve_alias(
            &a.target.name,
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
        target_spelling: a.target.name.clone(),
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
    if let Some(reference) = &ty.reference {
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
        return Ok(types.intern_reference(pointee, reference.mutable));
    }
    let target = if let Some(module) = &ty.module {
        let Some(target) = module_names.get(module).copied() else {
            return Err(Diagnostic::new(
                "E0221",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown module `{module}`"),
                Some(ty.span),
            ));
        };
        if imports[current.0 as usize].get(module) != Some(&target) {
            return Err(Diagnostic::new(
                "E0223",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("module `{module}` is not directly imported"),
                Some(ty.span),
            ));
        }
        target
    } else {
        current
    };
    if ty.module.is_none()
        && let Some(parameter) = generic_scope.get(&ty.name).copied()
    {
        if !ty.arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(parameter);
    }
    let mut arguments = Vec::with_capacity(ty.arguments.len());
    for argument in &ty.arguments {
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
    if ty.module.is_none()
        && let Some(expected) = intrinsic_type_arity(&ty.name)
    {
        if arguments.len() != expected {
            return Err(generic_arity(ty, expected));
        }
        let element = arguments[0];
        if types.contains_generic(element) {
            return Err(Diagnostic::new(
                if ty.name == "List" {
                    "E0310"
                } else if ty.name == "Array" {
                    "E0304"
                } else {
                    "E0283"
                },
                Phase::Semantic,
                DiagnosticCategory::Type,
                if matches!(ty.name.as_str(), "Array" | "List") {
                    collection_admission_message(
                        &ty.name,
                        element,
                        types.collection_element_admission(element),
                    )
                } else {
                    format!(
                        "{} element types must be concrete; generic capability constraints are deferred",
                        ty.name
                    )
                },
                Some(ty.span),
            ));
        }
        return match ty.name.as_str() {
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
                            element,
                            types.collection_element_admission(element),
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
                            element,
                            types.collection_element_admission(element),
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
            "View" => Ok(types.intern_view(element, false)),
            "ViewMut" => Ok(types.intern_view(element, true)),
            _ => unreachable!(),
        };
    }
    if let Some(id) = struct_names[target.0 as usize].get(&ty.name).copied() {
        let expected = struct_arities[id.0 as usize];
        if arguments.len() != expected {
            return Err(generic_arity(ty, expected));
        }
        if arguments
            .iter()
            .any(|argument| types.contains_reference(*argument) || types.contains_view(*argument))
        {
            return Err(restricted_generic_argument(ty.span));
        }
        return if expected == 0 {
            Ok(types
                .id_of(TypeData::Struct(id))
                .expect("collected struct type"))
        } else {
            Ok(types.intern_struct_instance(id, arguments))
        };
    }
    if let Some(id) = enum_names[target.0 as usize].get(&ty.name).copied() {
        let expected = enum_arities[id.0 as usize];
        if arguments.len() != expected {
            return Err(generic_arity(ty, expected));
        }
        if arguments
            .iter()
            .any(|argument| types.contains_reference(*argument) || types.contains_view(*argument))
        {
            return Err(restricted_generic_argument(ty.span));
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
        .and_then(|map| map.get(&ty.name))
        .copied()
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(alias);
    }
    if ty.module.is_none()
        && let Some(builtin) = builtin(&ty.name)
    {
        if !arguments.is_empty() {
            return Err(generic_arity(ty, 0));
        }
        return Ok(builtin);
    }
    Err(unknown_type(ty))
}

fn generic_arity(ty: &AstType, expected: usize) -> Diagnostic {
    Diagnostic::new(
        "E0261",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!(
            "type `{}` expects {expected} generic arguments, found {}",
            ty.name,
            ty.arguments.len()
        ),
        Some(ty.span),
    )
}

fn intrinsic_type_arity(name: &str) -> Option<usize> {
    matches!(name, "Buffer" | "Array" | "List" | "View" | "ViewMut").then_some(1)
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
    let mut seen = BTreeSet::new();
    parameters
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
        .collect()
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
                let available = [Capability::Copy, Capability::Relocatable]
                    .into_iter()
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
            TypeData::Reference { pointee: ty, .. }
            | TypeData::Buffer { element: ty }
            | TypeData::Array { element: ty }
            | TypeData::List { element: ty }
            | TypeData::View { element: ty, .. },
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
    match (types.get(pattern), types.get(actual)) {
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
            match types.get(ty) {
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
            TypeData::Integer(integer) => {
                let bytes = u64::from(integer.bits(target) / 8);
                TypeLayout {
                    size: bytes,
                    align: bytes,
                }
            }
            TypeData::Float(FloatType::Float32) => TypeLayout { size: 4, align: 4 },
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
            TypeData::Reference { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes,
                    align: bytes,
                }
            }
            TypeData::Buffer { .. } | TypeData::Array { .. } | TypeData::View { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes * 2,
                    align: bytes,
                }
            }
            TypeData::List { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                TypeLayout {
                    size: bytes * 3,
                    align: bytes,
                }
            }
            TypeData::GenericParam(_) => TypeLayout { size: 0, align: 1 },
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
    let mut types = std::mem::take(&mut d.types);
    for m in &d.program.modules {
        for f in m.ast.functions() {
            let id = FunctionId(functions.len() as u32);
            functions.push(
                analyze_function(f, id, m.info.id, &d, &mut types, target).map_err(|ds| {
                    ds.into_iter()
                        .map(|x| x.with_source_name(&m.info.source_name))
                        .collect::<Vec<_>>()
                })?,
            );
        }
    }
    let generic_functions = functions;
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
        modules: d.program.modules.iter().map(|m| m.info.clone()).collect(),
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
        let structurally_expands = self.queue.iter().any(|previous| {
            previous.function == key.function
                && previous.arguments.len() == key.arguments.len()
                && key
                    .arguments
                    .iter()
                    .zip(&previous.arguments)
                    .all(|(new, old)| type_contains(self.types, *new, *old))
                && key.arguments != previous.arguments
        });
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
                    };
                    Ok(HirStmt {
                        kind,
                        span: statement.span,
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
                        element_type,
                        checked,
                    } => Ok(HirPlaceProjection::Index {
                        index: Box::new(self.substitute_expr(index, substitution)?),
                        element_type: self.substitute_type(
                            *element_type,
                            substitution,
                            index.span,
                        )?,
                        checked: *checked,
                    }),
                })
                .collect::<Result<Vec<_>, Vec<Diagnostic>>>()?,
            ty: self.substitute_type(place.ty, substitution, Span::in_source(SourceId(0), 0, 0))?,
        })
    }

    fn substitute_expr(
        &mut self,
        expression: &HirExpr,
        substitution: &Substitution,
    ) -> Result<HirExpr, Vec<Diagnostic>> {
        let ty = self.substitute_type(expression.ty, substitution, expression.span)?;
        let kind = match &expression.kind {
            HirExprKind::Int(value) => HirExprKind::Int(*value),
            HirExprKind::Float(value) => HirExprKind::Float(*value),
            HirExprKind::Bool(value) => HirExprKind::Bool(*value),
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
                if !self.types.guarantees_copy(place.ty) {
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
            HirExprKind::BufferInit {
                element_type,
                length,
                initial,
            } => HirExprKind::BufferInit {
                element_type: self.substitute_type(*element_type, substitution, expression.span)?,
                length: Box::new(self.substitute_expr(length, substitution)?),
                initial: Box::new(self.substitute_expr(initial, substitution)?),
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
            HirExprKind::ListCapacity { source } => HirExprKind::ListCapacity {
                source: self.substitute_place(source, substitution)?,
            },
            HirExprKind::View { source, mutable } => HirExprKind::View {
                source: self.substitute_place(source, substitution)?,
                mutable: *mutable,
            },
            HirExprKind::Call {
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
                    callee: HirCallTarget::Instance(instance),
                    type_arguments: concrete_arguments,
                    args: args
                        .iter()
                        .map(|argument| self.substitute_expr(argument, substitution))
                        .collect::<Result<Vec<_>, _>>()?,
                }
            }
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
        Some(
            TypeData::Buffer { element }
            | TypeData::Array { element }
            | TypeData::List { element }
            | TypeData::View { element, .. },
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
            Some(
                TypeData::Buffer { element }
                | TypeData::Array { element }
                | TypeData::List { element }
                | TypeData::View { element, .. },
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
            TypeData::Integer(integer) => {
                let bytes = u64::from(integer.bits(target) / 8);
                Some(TypeLayout {
                    size: bytes,
                    align: bytes,
                })
            }
            TypeData::Float(FloatType::Float32) => Some(TypeLayout { size: 4, align: 4 }),
            TypeData::Float(FloatType::Float64) => Some(TypeLayout { size: 8, align: 8 }),
            TypeData::Struct(id) => Some(structs[id.0 as usize].layout),
            TypeData::Enum(id) => Some(enums[id.0 as usize].layout),
            TypeData::Reference { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes,
                    align: bytes,
                })
            }
            TypeData::Buffer { .. } | TypeData::Array { .. } | TypeData::View { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes * 2,
                    align: bytes,
                })
            }
            TypeData::List { .. } => {
                let bytes = u64::from(target.pointer_width / 8);
                Some(TypeLayout {
                    size: bytes * 3,
                    align: bytes,
                })
            }
            TypeData::GenericParam(_)
            | TypeData::StructInstance(_, _)
            | TypeData::EnumInstance(_, _) => None,
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
) -> Result<GenericHirFunction, Vec<Diagnostic>> {
    let sig = &d.signatures[id.0 as usize];
    let mut a = Analyzer {
        scopes: vec![BTreeMap::new()],
        locals: vec![],
        signatures: &d.signatures,
        names: &d.names,
        imports: &d.imports,
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
        target,
    };
    let mut parameters = vec![];
    for p in &sig.parameters {
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
            address_taken: false,
        });
        a.scopes[0].insert(p.name.clone(), local);
        parameters.push(HirParameter {
            local,
            ty: p.ty,
            span: p.span,
        });
    }
    let mut body = a.block(&f.body, false)?;
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
    Ok(GenericHirFunction {
        id,
        module,
        parameters,
        locals: a.locals,
        body,
        span: f.span,
    })
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
    };
    for parameter in parameters {
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
        for statement in &mut block.statements {
            match &mut statement.kind {
                HirStmtKind::Nop => {}
                HirStmtKind::Local { local, initializer } => {
                    self.expr(initializer)?;
                    if let Some(owner) = self.derived_owner(initializer) {
                        self.provenance[local.0 as usize] = Some(owner);
                        self.borrowed.last_mut().unwrap().insert(owner);
                        if self.is_list_storage_borrow(initializer) {
                            self.storage_borrowed.last_mut().unwrap().insert(owner);
                        }
                    }
                    if !self.types.guarantees_copy(self.locals[local.0 as usize].ty) {
                        self.buffer_lengths[local.0 as usize] = self.known_length(initializer);
                        self.state[local.0 as usize] = OwnerState::Owned;
                        self.active.push(*local);
                    } else if self
                        .types
                        .view_info(self.locals[local.0 as usize].ty)
                        .is_some()
                    {
                        self.buffer_lengths[local.0 as usize] = self.known_length(initializer);
                    }
                }
                HirStmtKind::Assign { place, value } => {
                    self.expr(value)?;
                    self.place(place, statement.span)?;
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
                }
                HirStmtKind::While { condition, body } => {
                    self.expr(condition)?;
                    let before = self.state.clone();
                    let before_lengths = self.buffer_lengths.clone();
                    self.block(body, true)?;
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
        if !nested {
            debug_assert!(self.borrowed.is_empty());
            debug_assert!(self.storage_borrowed.is_empty());
        }
        Ok(())
    }

    fn expr(&mut self, expr: &HirExpr) -> Result<(), Vec<Diagnostic>> {
        match &expr.kind {
            HirExprKind::Move(local) => self.move_local(*local, expr.span),
            HirExprKind::Local(local) => {
                if self.types.guarantees_copy(expr.ty) {
                    Ok(())
                } else {
                    self.require_owned(*local, expr.span)
                }
            }
            HirExprKind::Int(_) | HirExprKind::Float(_) | HirExprKind::Bool(_) => Ok(()),
            HirExprKind::Load(place) => self.place(place, expr.span),
            HirExprKind::Borrow { place, .. } | HirExprKind::View { source: place, .. } => {
                self.place(place, expr.span)
            }
            HirExprKind::BufferInit {
                length, initial, ..
            }
            | HirExprKind::ArrayFill {
                length, initial, ..
            } => {
                self.expr(length)?;
                self.expr(initial)
            }
            HirExprKind::ArrayInit { elements, .. } | HirExprKind::ListInit { elements, .. } => {
                for element in elements {
                    self.expr(element)?;
                }
                Ok(())
            }
            HirExprKind::ArrayLength { source }
            | HirExprKind::ListLength { source }
            | HirExprKind::ListCapacity { source } => self.place(source, expr.span),
            HirExprKind::Call { args, .. } => {
                for argument in args {
                    self.expr(argument)?;
                    if self
                        .types
                        .reference_info(argument.ty)
                        .is_some_and(|(pointee, mutable)| {
                            mutable && self.types.list_element(pointee).is_some()
                        })
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
                            "cannot pass a writable List reference to a call while a derived element reference/view remains live",
                            argument.span,
                        ));
                    }
                }
                Ok(())
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
            HirExprKind::Coerce { operand, .. }
            | HirExprKind::ExplicitCast { operand, .. }
            | HirExprKind::Unary { operand, .. } => self.expr(operand),
            HirExprKind::Binary { left, right, .. } => {
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
        for projection in &place.projections {
            if let HirPlaceProjection::Index { index, .. } = projection {
                self.expr(index)?;
                if let HirExprKind::Int(value) = index.kind
                    && let HirPlaceBase::Local(local) = place.base
                    && let Some(length) = self.buffer_lengths[local.0 as usize]
                    && u64::try_from(value).is_ok_and(|index| index >= length)
                {
                    return Err(self.error(
                        "E0296",
                        format!("constant index {value} is out of bounds for length {length}"),
                        index.span,
                    ));
                }
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
            HirExprKind::Borrow { place, .. } | HirExprKind::View { source: place, .. } => {
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

    fn is_list_storage_borrow(&self, expr: &HirExpr) -> bool {
        match &expr.kind {
            HirExprKind::Borrow { place, .. } => place
                .projections
                .iter()
                .any(|projection| matches!(projection, HirPlaceProjection::Index { .. })),
            HirExprKind::View { source, .. } => self.types.list_element(source.ty).is_some(),
            _ => false,
        }
    }

    fn known_length(&self, expr: &HirExpr) -> Option<u64> {
        match &expr.kind {
            HirExprKind::BufferInit { length, .. } | HirExprKind::ArrayFill { length, .. } => {
                match length.kind {
                    HirExprKind::Int(value) => u64::try_from(value).ok(),
                    _ => None,
                }
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
        if arguments.iter().any(|argument| {
            self.types.contains_reference(*argument) || self.types.contains_view(*argument)
        }) {
            return Err(vec![restricted_generic_argument(span)]);
        }
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
        if arguments.iter().any(|argument| {
            self.types.contains_reference(*argument) || self.types.contains_view(*argument)
        }) {
            return Err(vec![restricted_generic_argument(span)]);
        }
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
                });
                continue;
            }
            let kind = match &s.kind {
                AstStmtKind::Local {
                    ty,
                    name,
                    initializer,
                } => {
                    if self.scopes.last().is_some_and(|x| x.contains_key(name)) {
                        return Err(vec![duplicate("local", name, s.span)]);
                    }
                    let ty = self.resolve_source_type(ty)?;
                    let initializer = self.expression(initializer, Some(ty))?.expr;
                    let local = LocalId(self.locals.len() as u32);
                    self.locals.push(HirLocal {
                        id: local,
                        name: name.clone(),
                        ty,
                        span: s.span,
                        parameter: false,
                        address_taken: false,
                    });
                    self.scopes.last_mut().unwrap().insert(name.clone(), local);
                    HirStmtKind::Local { local, initializer }
                }
                AstStmtKind::Assign { place, value } => {
                    let place = self.resolve_expr_place(place, true)?;
                    if !self.types.guarantees_copy(place.ty)
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
                                .view_info(self.locals[local.0 as usize].ty)
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
                    HirStmtKind::Assign { place, value }
                }
                AstStmtKind::Expr(expression) => self.effect_statement(expression)?,
                AstStmtKind::If {
                    condition,
                    then_block,
                    else_block,
                } => HirStmtKind::If {
                    condition: self.expression(condition, Some(TypeId::BOOL))?.expr,
                    then_block: self.block(then_block, true)?,
                    else_block: else_block
                        .as_ref()
                        .map(|x| self.block(x, true))
                        .transpose()?,
                },
                AstStmtKind::While { condition, body } => HirStmtKind::While {
                    condition: self.expression(condition, Some(TypeId::BOOL))?.expr,
                    body: self.block(body, true)?,
                },
                AstStmtKind::Match {
                    mode,
                    scrutinee,
                    arms,
                } => self.match_statement(*mode, scrutinee, arms)?,
                AstStmtKind::Return(v) => HirStmtKind::Return {
                    value: self.expression(v, Some(self.return_type))?.expr,
                    drops: Vec::new(),
                },
            };
            let hs = HirStmt { kind, span: s.span };
            ended = statement_returns(&hs);
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
                "only push(...) and reserve(...) are admitted as effect statements",
                Some(expression.span),
            )]);
        };
        if !type_arguments.is_empty()
            || args.len() != 2
            || !matches!(callee.as_str(), "push" | "reserve")
        {
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
                module: arm.pattern.module.clone(),
                name: arm.pattern.enum_name.clone(),
                arguments: arm.pattern.type_arguments.clone(),
                reference: None,
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
            AstExprKind::Index { base, index } => {
                let mut place = self.resolve_expr_place(base, writable)?;
                let (element_type, mutable) =
                    if let Some(element) = self.types.buffer_element(place.ty) {
                        (element, true)
                    } else if let Some(element) = self.types.array_element(place.ty) {
                        (element, true)
                    } else if let Some(element) = self.types.list_element(place.ty) {
                        (element, true)
                    } else if let Some((element, mutable)) = self.types.view_info(place.ty) {
                        (element, mutable)
                    } else {
                        return Err(vec![Diagnostic::new(
                            "E0287",
                            Phase::Semantic,
                            DiagnosticCategory::Type,
                            format!(
                                "checked indexing requires Buffer/Array/List/View, found {}",
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
                let index = self.expression(index, Some(TypeId::USIZE))?.expr;
                place.projections.push(HirPlaceProjection::Index {
                    index: Box::new(index),
                    element_type,
                    checked: true,
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
        if let AstExprKind::CollectionLiteral(elements) = &e.kind {
            return self.collection_literal(elements, e.span, expected);
        }
        if let AstExprKind::Integer(t) = &e.kind {
            return self.integer(t, false, expected, e.span);
        }
        if let AstExprKind::Float(t) = &e.kind {
            return self.float(t, false, expected, e.span);
        }
        if let AstExprKind::Unary {
            op: AstUnaryOp::Negate,
            operand,
        } = &e.kind
        {
            if let AstExprKind::Integer(t) = &operand.kind {
                return self.integer(t, true, expected, e.span);
            }
            if let AstExprKind::Float(t) = &operand.kind {
                return self.float(t, true, expected, e.span);
            }
        }
        let c = match &e.kind {
            AstExprKind::Bool(v) => Checked {
                expr: HirExpr {
                    kind: HirExprKind::Bool(*v),
                    ty: TypeId::BOOL,
                    span: e.span,
                },
                constant: None,
            },
            AstExprKind::Name(n) => {
                if self.names[self.module.0 as usize].contains_key(n) {
                    return Err(vec![Diagnostic::new(
                        "E0215",
                        Phase::Semantic,
                        DiagnosticCategory::Unsupported,
                        "function values are not admitted",
                        Some(e.span),
                    )]);
                }
                let Some(l) = self.lookup(n) else {
                    return Err(vec![unknown_name(n, e.span)]);
                };
                Checked {
                    expr: HirExpr {
                        kind: if self.types.guarantees_copy(self.locals[l.0 as usize].ty) {
                            HirExprKind::Local(l)
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
                if callee == "length" {
                    return self.collection_length(type_arguments, args, e.span, expected);
                }
                if callee == "capacity" {
                    return self.list_capacity(type_arguments, args, e.span, expected);
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
                    self.call(callee, type_arguments, args, e.span)?
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
                if let AstExprKind::Field {
                    base: qualifier,
                    name: enum_name,
                    ..
                } = &base.kind
                    && let AstExprKind::Name(module) = &qualifier.kind
                    && self.lookup(module).is_none()
                    && self.module_names.contains_key(module)
                {
                    let enum_ty = self.qualified_enum_type(module, enum_name, &[], e.span)?;
                    self.enum_init(enum_ty, name, &[], false, e.span)?
                } else if let AstExprKind::Name(type_name) = &base.kind {
                    if let Some(enum_id) = self.local_enum_id(type_name) {
                        let enum_ty = self.nominal_enum_type(enum_id, Vec::new(), e.span)?;
                        self.enum_init(enum_ty, name, &[], false, e.span)?
                    } else {
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
                if let HirPlaceBase::Local(local) = &place.base
                    && !place
                        .projections
                        .iter()
                        .any(|projection| matches!(projection, HirPlaceProjection::Index { .. }))
                {
                    self.locals[local.0 as usize].address_taken = true;
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
            AstExprKind::Binary { op, left, right } => {
                self.binary(*op, left, right, expected, e.span)?
            }
            _ => unreachable!(),
        };
        self.coerce(c, expected)
    }

    fn load_place(&self, place: HirPlace, span: Span) -> Result<Checked, Vec<Diagnostic>> {
        if !self.types.guarantees_copy(place.ty) {
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
                TypeData::Bool
                | TypeData::Struct(_)
                | TypeData::Enum(_)
                | TypeData::GenericParam(_)
                | TypeData::StructInstance(_, _)
                | TypeData::EnumInstance(_, _)
                | TypeData::Reference { .. }
                | TypeData::Buffer { .. }
                | TypeData::Array { .. }
                | TypeData::List { .. }
                | TypeData::View { .. },
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

    fn collection_literal(
        &mut self,
        elements: &[AstExpr],
        span: Span,
        expected: Option<TypeId>,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let Some(collection_type) = expected else {
            return Err(vec![Diagnostic::new(
                "E0305",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "collection literal requires an expected Array<T> or List<T> type",
                Some(span),
            )]);
        };
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
        Ok(Checked {
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
        })
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
        if self.types.contains_generic(element) {
            return Err(vec![Diagnostic::new(
                "E0304",
                Phase::Semantic,
                DiagnosticCategory::Type,
                "Vertical-16 Array fill element type must be concrete; stored-borrow freedom cannot yet be proven symbolically",
                Some(span),
            )]);
        }
        if !self.types.is_admitted_array_element(element) {
            return Err(vec![Diagnostic::new(
                "E0304",
                Phase::Semantic,
                DiagnosticCategory::Type,
                collection_admission_message(
                    "Array",
                    self.type_name(element),
                    self.types.collection_element_admission(element),
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
        if let Some(ConstantValue::Integer(length_value)) = length.constant {
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
        let Some(element) = self.types.owning_contiguous_element(source.ty) else {
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
    ) -> Result<Checked, Vec<Diagnostic>> {
        let Some(id) = self.names[self.module.0 as usize].get(n).copied() else {
            return Err(vec![Diagnostic::new(
                "E0212",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown function `{n}`"),
                Some(span),
            )]);
        };
        self.call_id(id, n, type_arguments, args, span)
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
            module: Some(module.into()),
            name: name.into(),
            arguments: arguments.to_vec(),
            reference: None,
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
        let Some(mid) = self.module_names.get(m).copied() else {
            return Err(vec![Diagnostic::new(
                "E0221",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("unknown module `{m}`"),
                Some(span),
            )]);
        };
        if self.imports[self.module.0 as usize].get(m) != Some(&mid) {
            return Err(vec![Diagnostic::new(
                "E0223",
                Phase::Semantic,
                DiagnosticCategory::Name,
                format!("module `{m}` is not directly imported"),
                Some(span),
            )]);
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
        if args.len() != s.parameters.len() {
            return Err(vec![Diagnostic::new(
                "E0213",
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "function `{name}` expects {} arguments, found {}",
                    s.parameters.len(),
                    args.len()
                ),
                Some(span),
            )]);
        }
        let mut type_arguments = self.resolve_type_arguments(source_type_arguments)?;
        let mut prechecked = None;
        let inferred_application =
            source_type_arguments.is_empty() && !s.generic_parameters.is_empty();
        if inferred_application {
            let checked = args
                .iter()
                .map(|argument| self.expression(argument, None))
                .collect::<Result<Vec<_>, _>>()?;
            let mut inferred = BTreeMap::new();
            for (parameter, argument) in s.parameters.iter().zip(&checked) {
                infer_generic_arguments(self.types, parameter.ty, argument.expr.ty, &mut inferred)?;
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
        if type_arguments.iter().any(|argument| {
            self.types.contains_reference(*argument) || self.types.contains_view(*argument)
        }) {
            return Err(vec![restricted_generic_argument(span)]);
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
        let mut out = vec![];
        for (index, (a, concrete_ty)) in args.iter().zip(concrete_parameters).enumerate() {
            let checked = if let Some(values) = &prechecked {
                self.coerce(values[index].clone(), Some(concrete_ty))
            } else {
                self.expression(a, Some(concrete_ty))
            };
            match checked {
                Ok(x) => out.push(x.expr),
                Err(mut ds) => {
                    if let Some(d) = ds.first_mut() {
                        d.code = "E0214";
                        d.message = format!(
                            "argument {} to `{name}` requires {}: {}",
                            index + 1,
                            self.type_name(concrete_ty),
                            d.message
                        )
                    }
                    return Err(ds);
                }
            }
        }
        Ok(Checked {
            expr: HirExpr {
                kind: HirExprKind::Call {
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
    fn binary(
        &mut self,
        op: AstBinaryOp,
        la: &AstExpr,
        ra: &AstExpr,
        expected: Option<TypeId>,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let ll = literal(la);
        let rl = literal(ra);
        let (l, r) = if ll && !rl {
            let r = self.expression(ra, None)?;
            (self.expression(la, Some(r.expr.ty))?, r)
        } else if rl && !ll {
            let l = self.expression(la, None)?;
            let r = self.expression(ra, Some(l.expr.ty))?;
            (l, r)
        } else if ll && rl {
            let c = expected.filter(|t| self.types.is_numeric(*t));
            (self.expression(la, c)?, self.expression(ra, c)?)
        } else {
            (self.expression(la, None)?, self.expression(ra, None)?)
        };
        let equality = matches!(op, AstBinaryOp::Equal | AstBinaryOp::NotEqual);
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
    fn coerce(&self, c: Checked, expected: Option<TypeId>) -> Result<Checked, Vec<Diagnostic>> {
        let Some(to) = expected else { return Ok(c) };
        if c.expr.ty == to {
            return Ok(c);
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
        _ => return None,
    })
}
fn unknown_type(t: &AstType) -> Diagnostic {
    Diagnostic::new(
        "E0204",
        Phase::Semantic,
        DiagnosticCategory::Type,
        format!("unknown type `{}`", t.name),
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
        CollectionElementAdmission::ForbiddenBorrow => format!(
            "{collection} cannot persist borrowed element type {element}; stored references and views require lifetime support not available in Vertical-16"
        ),
        CollectionElementAdmission::SymbolicStorageUnknown => format!(
            "{collection} element type {element} is symbolically Relocatable, but its stored-borrow freedom cannot be proven; Vertical-16 keeps symbolic collection storage conservative"
        ),
        CollectionElementAdmission::MissingRelocatable => format!(
            "{collection} element type {element} does not provide the Relocatable capability required for owning collection storage"
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
    let mut names = BTreeSet::new();
    let mut sources = BTreeSet::new();
    for (i, m) in p.modules.iter().enumerate() {
        if m.info.id.0 as usize != i
            || !names.insert(&m.info.name)
            || !sources.insert(m.info.source)
        {
            return Err(fail("duplicate or non-canonical module/source identity"));
        }
        let mut imports = BTreeSet::new();
        for x in &m.info.imports {
            if x.module.0 as usize >= p.modules.len()
                || p.modules[x.module.0 as usize].info.name != x.name
                || !imports.insert(&x.name)
            {
                return Err(vec![
                    Diagnostic::new(
                        "E0220",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!("duplicate or invalid import `{}`", x.name),
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
        TypeData::Array { element } => !h.types.is_admitted_array_element(*element),
        TypeData::List { element } => !h.types.is_admitted_list_element(*element),
        _ => false,
    }) {
        return Err(fail(
            "HIR contains a Buffer/View/Array/List with an inadmissible element type".into(),
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
        verify_block(
            &f.body,
            f,
            s.return_type,
            &h.instances,
            &h.structs,
            &h.enums,
            &h.types,
            &fail,
        )?
    }
    Ok(())
}
fn verify_block(
    b: &HirBlock,
    f: &HirFunction,
    ret: TypeId,
    sigs: &[FunctionInstanceInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
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
                if matches!(place.base, HirPlaceBase::Dereference { mutable: false, .. }) {
                    return Err(fail("HIR writes through a shared reference".into()));
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
                verify_block(then_block, f, ret, sigs, structs, enums, types, fail)?;
                if let Some(x) = else_block {
                    verify_block(x, f, ret, sigs, structs, enums, types, fail)?
                }
            }
            HirStmtKind::While { condition, body } => {
                verify_expr(condition, f, sigs, structs, enums, types, fail)?;
                if condition.ty != TypeId::BOOL {
                    return Err(fail("HIR condition not bool".into()));
                }
                verify_block(body, f, ret, sigs, structs, enums, types, fail)?
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
                    verify_block(&arm.body, f, ret, sigs, structs, enums, types, fail)?;
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
        }
    }
    Ok(())
}
fn verify_expr(
    e: &HirExpr,
    f: &HirFunction,
    sigs: &[FunctionInstanceInfo],
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
        HirExprKind::Int(_) if types.integer_info(e.ty).is_none() => {
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
            if place.ty != e.ty {
                return Err(fail("HIR load/place type mismatch".into()));
            }
        }
        HirExprKind::Borrow { place, mutable } => {
            verify_place(place, f, sigs, structs, enums, types, fail)?;
            if types.reference_info(e.ty) != Some((place.ty, *mutable)) {
                return Err(fail("HIR borrow type/capability mismatch".into()));
            }
            if *mutable && matches!(place.base, HirPlaceBase::Dereference { mutable: false, .. }) {
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
        HirExprKind::ListLength { source } | HirExprKind::ListCapacity { source } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            if types.list_element(source.ty).is_none() || e.ty != TypeId::USIZE {
                return Err(fail("HIR List metadata query contract invalid".into()));
            }
        }
        HirExprKind::View { source, mutable } => {
            verify_place(source, f, sigs, structs, enums, types, fail)?;
            let Some(element) = types.owning_contiguous_element(source.ty) else {
                return Err(fail("HIR View source is not Buffer/Array/List".into()));
            };
            if types.view_info(e.ty) != Some((element, *mutable)) {
                return Err(fail("HIR View type/capability mismatch".into()));
            }
        }
        HirExprKind::Call { callee, args, .. } => {
            let HirCallTarget::Instance(callee) = callee else {
                return Err(fail("concrete HIR contains declaration call".into()));
            };
            let Some(s) = sigs.get(callee.0 as usize) else {
                return Err(fail("HIR callee missing".into()));
            };
            if s.return_type != e.ty || args.len() != s.parameters.len() {
                return Err(fail("HIR call mismatch".into()));
            }
            for (a, p) in args.iter().zip(&s.parameters) {
                verify_expr(a, f, sigs, structs, enums, types, fail)?;
                if a.ty != p.ty {
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
                    (left.ty == TypeId::BOOL || types.is_numeric(left.ty)) && e.ty == TypeId::BOOL
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

fn verify_place(
    place: &HirPlace,
    function: &HirFunction,
    sigs: &[FunctionInstanceInfo],
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
                element_type,
                checked,
            } => {
                verify_expr(index, function, sigs, structs, enums, types, fail)?;
                let element = types
                    .buffer_element(ty)
                    .or_else(|| types.array_element(ty))
                    .or_else(|| types.list_element(ty))
                    .or_else(|| types.view_info(ty).map(|(element, _)| element))
                    .ok_or_else(|| fail("HIR index projection has non-contiguous base".into()))?;
                if index.ty != TypeId::USIZE || element != *element_type || !*checked {
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
        HirStmtKind::Return { .. } => true,
        HirStmtKind::If {
            then_block,
            else_block: Some(e),
            ..
        } => definitely_returns(then_block) && definitely_returns(e),
        HirStmtKind::Match { arms, .. } => {
            !arms.is_empty() && arms.iter().all(|arm| definitely_returns(&arm.body))
        }
        _ => false,
    }
}
fn definitely_returns(b: &HirBlock) -> bool {
    b.statements.last().is_some_and(statement_returns)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{SourceFile, parse_source};
    fn check(s: &str) -> Result<TypedHir, Vec<Diagnostic>> {
        analyze(parse_source(&SourceFile::new("test.ae", s)).unwrap())
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
            address_taken: false,
        });
        assert!(verify_hir(&h).is_err());
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
}
