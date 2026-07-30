//! Schema-v1 serialization DTOs shared with the Python IR boundary.
//!
//! These types describe only the wire representation. They deliberately do not
//! convert to the owned Rust IR or perform semantic verification.

use std::fmt;

use serde::de::{Error as _, Visitor};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// The frozen Python/Rust interchange schema version represented here.
pub const IR_SCHEMA_VERSION: i64 = 1;

fn is_false(value: &bool) -> bool {
    !*value
}

fn contains_storage(value: &serde_json::Value) -> bool {
    match value {
        serde_json::Value::Array(items) => items.iter().any(contains_storage),
        serde_json::Value::Object(mapping) => {
            matches!(
                mapping.get("tag"),
                Some(serde_json::Value::String(tag)) if tag == "storage"
            ) || mapping.values().any(contains_storage)
        }
        _ => false,
    }
}

#[derive(Deserialize)]
#[serde(untagged)]
enum NullableDTORepresentation<T> {
    Value(T),
    Null(()),
}

/// A required JSON field whose value may explicitly be `null`.
///
/// Serde normally treats a missing `Option<T>` field like an explicit `null`.
/// The Python DTO contract distinguishes those cases, so this transparent
/// wrapper keeps nullable fields required while preserving their JSON shape.
#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(transparent)]
pub struct NullableDTO<T>(pub Option<T>);

impl<'de, T> Deserialize<'de> for NullableDTO<T>
where
    T: Deserialize<'de>,
{
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        NullableDTORepresentation::deserialize(deserializer).map(|representation| {
            match representation {
                NullableDTORepresentation::Value(value) => Self(Some(value)),
                NullableDTORepresentation::Null(()) => Self(None),
            }
        })
    }
}

/// A JSON floating-point token, distinct from an integer token.
///
/// The Python DTO contract rejects integer primitives in floating-point fields.
/// This transparent wrapper retains that distinction during serde decoding.
#[derive(Clone, Debug, PartialEq)]
pub struct IRFloatDTO(pub f64);

impl Serialize for IRFloatDTO {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.0.is_finite() {
            serializer.serialize_f64(self.0)
        } else {
            Err(<S::Error as serde::ser::Error>::custom(
                "floating-point DTO value must be finite",
            ))
        }
    }
}

impl<'de> Deserialize<'de> for IRFloatDTO {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct IRFloatDTOVisitor;

        impl Visitor<'_> for IRFloatDTOVisitor {
            type Value = IRFloatDTO;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a finite floating-point JSON token")
            }

            fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
            where
                E: serde::de::Error,
            {
                if value.is_finite() {
                    Ok(IRFloatDTO(value))
                } else {
                    Err(E::custom("floating-point DTO value must be finite"))
                }
            }
        }

        deserializer.deserialize_any(IRFloatDTOVisitor)
    }
}

fn deserialize_schema_version<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: Deserializer<'de>,
{
    let schema_version = i64::deserialize(deserializer)?;
    if schema_version == IR_SCHEMA_VERSION {
        Ok(schema_version)
    } else {
        Err(D::Error::custom(format_args!(
            "unsupported IR DTO schema version {schema_version}; expected {IR_SCHEMA_VERSION}"
        )))
    }
}

/// Complete schema-versioned module envelope.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRModuleDTO {
    /// Interchange schema version carried by the document.
    #[serde(deserialize_with = "deserialize_schema_version")]
    pub schema_version: i64,
    /// Functions in retained module order.
    pub functions: Vec<IRFunctionDTO>,
    /// Struct definitions in retained module order.
    pub structs: Vec<IRStructDefinitionDTO>,
}

fn deserialize_ssa_representation<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: Deserializer<'de>,
{
    let representation = String::deserialize(deserializer)?;
    if representation == "aether_ssa" {
        Ok(representation)
    } else {
        Err(D::Error::custom(format_args!(
            "unsupported SSA representation '{representation}'; expected 'aether_ssa'"
        )))
    }
}

/// Complete schema-versioned SSA module envelope.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct SSAModuleDTO {
    /// Interchange schema version.
    #[serde(deserialize_with = "deserialize_schema_version")]
    pub schema_version: i64,
    /// Canonical representation discriminator.
    #[serde(deserialize_with = "deserialize_ssa_representation")]
    pub representation: String,
    /// Functions in retained module order.
    pub functions: Vec<SSAFunctionDTO>,
    /// Nominal definitions in retained module order.
    pub structs: Vec<IRStructDefinitionDTO>,
}

/// Function container for value-based SSA.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub struct SSAFunctionDTO {
    pub name: String,
    pub parameters: Vec<IRParameterDTO>,
    pub return_type: IRTypeDTO,
    pub blocks: Vec<SSABasicBlockDTO>,
    pub entry_block: String,
    #[serde(default, skip_serializing_if = "is_false")]
    pub may_throw: bool,
}

/// One SSA block in deterministic retained order.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub struct SSABasicBlockDTO {
    pub name: String,
    pub instructions: Vec<SSAInstructionDTO>,
}

/// One predecessor-labelled phi incoming value.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub struct SSAPhiIncomingDTO {
    pub block: String,
    pub value: IRValueDTO,
}

/// SSA-only instructions and explicit exceptional terminators.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs, clippy::large_enum_variant)]
pub enum SSAControlInstructionDTO {
    Phi {
        result: IRValueDTO,
        incoming: Vec<SSAPhiIncomingDTO>,
    },
    Invoke {
        function: String,
        arguments: Vec<IRValueDTO>,
        result: NullableDTO<IRValueDTO>,
        exception: IRValueDTO,
        normal_target: String,
        exceptional_target: String,
        builtin: NullableDTO<String>,
        source_location: NullableDTO<IRSourceLocationDTO>,
        normal_arguments: Vec<IRValueDTO>,
        exceptional_arguments: Vec<IRValueDTO>,
    },
    InvokeIndirect {
        callee: IRValueDTO,
        arguments: Vec<IRValueDTO>,
        result: NullableDTO<IRValueDTO>,
        exception: IRValueDTO,
        normal_target: String,
        exceptional_target: String,
        normal_arguments: Vec<IRValueDTO>,
        exceptional_arguments: Vec<IRValueDTO>,
    },
    InvokeInterface {
        receiver: IRValueDTO,
        arguments: Vec<IRValueDTO>,
        slot: IRWitnessMethodSlotDTO,
        result: NullableDTO<IRValueDTO>,
        exception: IRValueDTO,
        normal_target: String,
        exceptional_target: String,
        normal_arguments: Vec<IRValueDTO>,
        exceptional_arguments: Vec<IRValueDTO>,
    },
    Throw {
        event: IRValueDTO,
        target: NullableDTO<String>,
        exceptional_arguments: Vec<IRValueDTO>,
    },
    Rethrow {
        event: IRValueDTO,
        target: NullableDTO<String>,
        exceptional_arguments: Vec<IRValueDTO>,
    },
    Propagate {
        event: IRValueDTO,
        target: NullableDTO<String>,
        exceptional_arguments: Vec<IRValueDTO>,
    },
}

/// Strict SSA instruction DTO. Ordinary value instructions reuse the frozen IR
/// DTO variants; SSA-only control instructions use [`SSAControlInstructionDTO`].
#[derive(Clone, Debug, PartialEq)]
pub enum SSAInstructionDTO {
    /// SSA-only control or phi instruction.
    Control(SSAControlInstructionDTO),
    /// Ordinary value instruction shared with Initial IR's wire vocabulary.
    Ordinary(IRInstructionDTO),
}

impl Serialize for SSAInstructionDTO {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self {
            Self::Control(instruction) => instruction.serialize(serializer),
            Self::Ordinary(instruction) => instruction.serialize(serializer),
        }
    }
}

impl<'de> Deserialize<'de> for SSAInstructionDTO {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = serde_json::Value::deserialize(deserializer)?;
        if contains_storage(&value) {
            return Err(D::Error::custom(
                "owning Initial IR storage is not legal SSA",
            ));
        }
        if let Ok(instruction) = serde_json::from_value::<SSAControlInstructionDTO>(value.clone()) {
            return Ok(Self::Control(instruction));
        }
        let instruction =
            serde_json::from_value::<IRInstructionDTO>(value).map_err(D::Error::custom)?;
        if matches!(
            instruction,
            IRInstructionDTO::Load { .. }
                | IRInstructionDTO::Store { .. }
                | IRInstructionDTO::InitDefault { .. }
                | IRInstructionDTO::CopyInit { .. }
                | IRInstructionDTO::MoveInit { .. }
                | IRInstructionDTO::Assign { .. }
                | IRInstructionDTO::Destroy { .. }
                | IRInstructionDTO::Relocate { .. }
                | IRInstructionDTO::Invoke { .. }
                | IRInstructionDTO::InvokeIndirect { .. }
                | IRInstructionDTO::InvokeInterface { .. }
                | IRInstructionDTO::Throw { .. }
                | IRInstructionDTO::Rethrow { .. }
                | IRInstructionDTO::Propagate { .. }
                | IRInstructionDTO::Call {
                    may_throw: true,
                    ..
                }
                | IRInstructionDTO::Return {
                    transferred_storage: NullableDTO(Some(_)),
                    ..
                }
        ) {
            return Err(D::Error::custom(
                "Initial IR lifecycle or exceptional-control shape is not legal SSA",
            ));
        }
        Ok(Self::Ordinary(instruction))
    }
}

/// Nominal struct definition in the wire schema.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRStructDefinitionDTO {
    /// Struct name.
    pub name: String,
    /// Fields in declaration order.
    pub fields: Vec<IRStructFieldDTO>,
}

/// One named struct field.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRStructFieldDTO {
    /// Field name.
    pub name: String,
    /// Field type.
    #[serde(rename = "type")]
    pub r#type: IRTypeDTO,
}

/// Canonical witness metadata carried by interface construction.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRWitnessTableDTO {
    /// Stable private LLVM symbol.
    pub symbol: String,
    /// Canonical implemented-interface identifier.
    pub interface_id: String,
    /// Canonical concrete-type identifier.
    pub concrete_type_id: String,
    /// Reserved carrier representation.
    pub carrier_kind: String,
    /// Future dispatch slots in declaration order.
    pub method_slots: Vec<IRWitnessMethodSlotDTO>,
    /// Native interface ABI version.
    pub abi_version: i64,
    /// Private erased box layout for struct-backed carriers.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub box_layout: Option<IRErasedBoxLayoutDTO>,
}

/// Strict wire representation of erased struct box metadata.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRErasedBoxLayoutDTO {
    /// Bytes occupied by the concrete payload.
    pub payload_size: i64,
    /// Required payload alignment.
    pub payload_alignment: i64,
    /// Byte offset from box base to payload.
    pub payload_offset: i64,
    /// Canonical ownership policy.
    pub ownership: String,
    /// Stable erased clone adapter.
    pub copy_owned_symbol: String,
    /// Stable erased destruction adapter.
    pub drop_owned_symbol: String,
}

/// One declaration-ordered future dispatch slot.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRWitnessMethodSlotDTO {
    /// Zero-based declaration-order slot.
    pub index: i64,
    /// Stable nominal method identifier.
    pub method_id: String,
    /// Erased parameter types.
    pub parameter_types: Vec<IRTypeDTO>,
    /// Erased result type.
    pub return_type: IRTypeDTO,
    /// Stable private erased thunk symbol.
    pub thunk_symbol: String,
    /// Receiver ownership in the erased ABI.
    pub receiver_ownership: String,
}

/// Function container in the wire schema.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRFunctionDTO {
    /// Function name.
    pub name: String,
    /// Parameters in declaration order.
    pub parameters: Vec<IRParameterDTO>,
    /// Declared return type.
    pub return_type: IRTypeDTO,
    /// Basic blocks in retained order.
    pub blocks: Vec<IRBasicBlockDTO>,
    /// Conservative internal catchable-exception effect.
    #[serde(default, skip_serializing_if = "is_false")]
    pub may_throw: bool,
}

/// Basic block in the wire schema.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub struct IRBasicBlockDTO {
    /// Block name.
    pub name: String,
    /// Instructions in program order.
    pub instructions: Vec<IRInstructionDTO>,
}

/// Complete tagged IR type representation.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IRTypeDTO {
    Int {},
    Float {},
    Double {},
    Bool {},
    String {},
    Void {},
    ExceptionEvent {},
    Function {
        parameter_types: Vec<Self>,
        return_type: Box<Self>,
    },
    Complex {},
    Nullable {
        inner: Box<Self>,
    },
    List {
        element: Box<Self>,
    },
    Array {
        element: Box<Self>,
    },
    Vector {
        element: Box<Self>,
        orientation: NullableDTO<String>,
    },
    Matrix {
        element: Box<Self>,
    },
    Struct {
        name: String,
    },
    MethodResult {
        receiver: Box<Self>,
        value: Box<Self>,
    },
    ClassRef {
        name: String,
    },
    Interface {
        name: String,
    },
    Enum {
        name: String,
        variants: Vec<String>,
        display_name: NullableDTO<String>,
    },
}

/// Tagged immutable value, owning storage, or parameter reference.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IRValueDTO {
    Value {
        name: String,
        #[serde(rename = "type")]
        r#type: IRTypeDTO,
    },
    Storage {
        name: String,
        #[serde(rename = "type")]
        r#type: IRTypeDTO,
    },
    Parameter {
        name: String,
        #[serde(rename = "type")]
        r#type: IRTypeDTO,
    },
}

/// Tagged owning storage representation used where the Python schema requires storage.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IRStorageDTO {
    Storage {
        name: String,
        #[serde(rename = "type")]
        r#type: IRTypeDTO,
    },
}

/// Tagged parameter representation used by function declarations.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IRParameterDTO {
    Parameter {
        name: String,
        #[serde(rename = "type")]
        r#type: IRTypeDTO,
    },
}

/// Tagged source location representation.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IRSourceLocationDTO {
    SourceLocation {
        line: i64,
        column: i64,
        path: NullableDTO<String>,
    },
}

/// Nominal enum constant metadata.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IREnumConstantDTO {
    EnumConstant {
        enum_name: String,
        member_name: String,
        member_id: i32,
        discriminant: i32,
    },
}

/// Tagged scalar or nominal constant payload.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(tag = "tag", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs)]
pub enum IRConstantDTO {
    Null,
    Bool {
        value: bool,
    },
    Int {
        value: i32,
    },
    Float {
        value: IRFloatDTO,
    },
    Complex {
        real: IRFloatDTO,
        imaginary: IRFloatDTO,
    },
    String {
        value: String,
    },
    Enum {
        value: IREnumConstantDTO,
    },
}

/// All 68 schema-v1 instruction variants with their stable Python DTO tags.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
#[allow(missing_docs, clippy::large_enum_variant)]
pub enum IRInstructionDTO {
    Const {
        result: IRValueDTO,
        value: IRConstantDTO,
    },
    Load {
        result: IRValueDTO,
        slot: IRValueDTO,
    },
    Store {
        slot: IRValueDTO,
        value: IRValueDTO,
    },
    InitDefault {
        destination: IRStorageDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    CopyInit {
        destination: IRStorageDTO,
        source: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    MoveInit {
        destination: IRStorageDTO,
        source: IRStorageDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    Assign {
        destination: IRStorageDTO,
        source: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    Destroy {
        value: IRStorageDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    Relocate {
        destination: IRStorageDTO,
        source: IRStorageDTO,
        count: i64,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    BinaryOp {
        result: IRValueDTO,
        operator: String,
        left: IRValueDTO,
        right: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    UnaryOp {
        result: IRValueDTO,
        operator: String,
        operand: IRValueDTO,
    },
    CompareOp {
        result: IRValueDTO,
        operator: String,
        left: IRValueDTO,
        right: IRValueDTO,
        aggregate_shape: NullableDTO<Vec<i64>>,
    },
    Cast {
        result: IRValueDTO,
        value: IRValueDTO,
    },
    Call {
        function: String,
        arguments: Vec<IRValueDTO>,
        result: NullableDTO<IRValueDTO>,
        builtin: NullableDTO<String>,
        source_location: NullableDTO<IRSourceLocationDTO>,
        #[serde(default, skip_serializing_if = "is_false")]
        may_throw: bool,
    },
    Invoke {
        function: String,
        arguments: Vec<IRValueDTO>,
        result: NullableDTO<IRValueDTO>,
        exception: IRValueDTO,
        normal_target: String,
        exceptional_target: String,
        exceptional_target_event: IRValueDTO,
        builtin: NullableDTO<String>,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    FunctionRef {
        result: IRValueDTO,
        function: String,
    },
    CallIndirect {
        callee: IRValueDTO,
        arguments: Vec<IRValueDTO>,
        result: NullableDTO<IRValueDTO>,
    },
    InvokeIndirect {
        callee: IRValueDTO,
        arguments: Vec<IRValueDTO>,
        result: NullableDTO<IRValueDTO>,
        exception: IRValueDTO,
        normal_target: String,
        exceptional_target: String,
        exceptional_target_event: IRValueDTO,
    },
    Print {
        value: IRValueDTO,
        newline: bool,
        aggregate_shape: NullableDTO<Vec<i64>>,
    },
    StructNew {
        result: IRValueDTO,
        fields: Vec<IRValueDTO>,
    },
    ClassNew {
        result: IRValueDTO,
    },
    ClassGet {
        result: IRValueDTO,
        object: IRValueDTO,
        field_index: i64,
        field_name: String,
    },
    ClassSet {
        object: IRValueDTO,
        field_index: i64,
        field_name: String,
        value: IRValueDTO,
        initialize: bool,
    },
    InterfaceConstruct {
        result: IRValueDTO,
        carrier: IRValueDTO,
        witness: IRWitnessTableDTO,
    },
    InterfaceCall {
        receiver: IRValueDTO,
        arguments: Vec<IRValueDTO>,
        slot: IRWitnessMethodSlotDTO,
        result: NullableDTO<IRValueDTO>,
    },
    InvokeInterface {
        receiver: IRValueDTO,
        arguments: Vec<IRValueDTO>,
        slot: IRWitnessMethodSlotDTO,
        result: NullableDTO<IRValueDTO>,
        exception: IRValueDTO,
        normal_target: String,
        exceptional_target: String,
        exceptional_target_event: IRValueDTO,
    },
    StructGet {
        result: IRValueDTO,
        #[serde(rename = "struct")]
        r#struct: IRValueDTO,
        field_index: i64,
        field_name: String,
    },
    StructSet {
        result: IRValueDTO,
        #[serde(rename = "struct")]
        r#struct: IRValueDTO,
        field_index: i64,
        field_name: String,
        value: IRValueDTO,
    },
    MethodResultNew {
        result: IRValueDTO,
        receiver: IRValueDTO,
        value: NullableDTO<IRValueDTO>,
    },
    MethodResultReceiver {
        result: IRValueDTO,
        method_result: IRValueDTO,
    },
    MethodResultValue {
        result: IRValueDTO,
        method_result: IRValueDTO,
    },
    ArrayNew {
        result: IRValueDTO,
        elements: Vec<IRValueDTO>,
    },
    ListNew {
        result: IRValueDTO,
        elements: Vec<IRValueDTO>,
    },
    ArrayCopy {
        result: IRValueDTO,
        array: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    ListCopy {
        result: IRValueDTO,
        list_value: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    ListContains {
        result: IRValueDTO,
        list_value: IRValueDTO,
        value: IRValueDTO,
    },
    ListIndexOf {
        result: IRValueDTO,
        list_value: IRValueDTO,
        value: IRValueDTO,
    },
    ListClear {
        list_value: IRValueDTO,
    },
    ListPush {
        list_value: IRValueDTO,
        value: IRValueDTO,
    },
    ListInsert {
        list_value: IRValueDTO,
        index: IRValueDTO,
        value: IRValueDTO,
    },
    ListRemoveAt {
        result: IRValueDTO,
        list_value: IRValueDTO,
        index: IRValueDTO,
    },
    ListPop {
        result: IRValueDTO,
        list_value: IRValueDTO,
    },
    ListReverse {
        list_value: IRValueDTO,
    },
    SequenceSort {
        sequence: IRValueDTO,
    },
    ArrayGet {
        result: IRValueDTO,
        array: IRValueDTO,
        index: IRValueDTO,
        borrowed: bool,
        borrow_scope: NullableDTO<String>,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    ArraySlice {
        result: IRValueDTO,
        array: IRValueDTO,
        start: IRValueDTO,
        end: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    ListSlice {
        result: IRValueDTO,
        list_value: IRValueDTO,
        start: IRValueDTO,
        end: IRValueDTO,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    ListGet {
        result: IRValueDTO,
        list_value: IRValueDTO,
        index: IRValueDTO,
        borrowed: bool,
        borrow_scope: NullableDTO<String>,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    ArraySet {
        array: IRValueDTO,
        index: IRValueDTO,
        value: IRValueDTO,
    },
    ListSet {
        list_value: IRValueDTO,
        index: IRValueDTO,
        value: IRValueDTO,
    },
    ArrayLength {
        result: IRValueDTO,
        array: IRValueDTO,
    },
    ListLength {
        result: IRValueDTO,
        list_value: IRValueDTO,
    },
    ListIsEmpty {
        result: IRValueDTO,
        list_value: IRValueDTO,
    },
    VectorNew {
        result: IRValueDTO,
        elements: Vec<IRValueDTO>,
        orientation: NullableDTO<String>,
    },
    MatrixNew {
        result: IRValueDTO,
        elements: Vec<IRValueDTO>,
        shape: [i64; 2],
    },
    VectorAdd {
        result: IRValueDTO,
        left: IRValueDTO,
        right: IRValueDTO,
        shape: [i64; 1],
        orientation: NullableDTO<String>,
    },
    VectorSub {
        result: IRValueDTO,
        left: IRValueDTO,
        right: IRValueDTO,
        shape: [i64; 1],
        orientation: NullableDTO<String>,
    },
    VectorScale {
        result: IRValueDTO,
        vector: IRValueDTO,
        scalar: IRValueDTO,
        shape: [i64; 1],
        orientation: NullableDTO<String>,
    },
    VectorDot {
        result: IRValueDTO,
        left: IRValueDTO,
        right: IRValueDTO,
        shape: [i64; 1],
    },
    OuterProduct {
        result: IRValueDTO,
        column: IRValueDTO,
        row: IRValueDTO,
        shape: [i64; 2],
    },
    MatrixAdd {
        result: IRValueDTO,
        left: IRValueDTO,
        right: IRValueDTO,
        shape: [i64; 2],
    },
    MatrixSub {
        result: IRValueDTO,
        left: IRValueDTO,
        right: IRValueDTO,
        shape: [i64; 2],
    },
    MatrixScale {
        result: IRValueDTO,
        matrix: IRValueDTO,
        scalar: IRValueDTO,
        shape: [i64; 2],
    },
    MatrixMatMul {
        result: IRValueDTO,
        left: IRValueDTO,
        right: IRValueDTO,
        shape: [i64; 3],
    },
    MatrixVectorMul {
        result: IRValueDTO,
        matrix: IRValueDTO,
        vector: IRValueDTO,
        shape: [i64; 2],
    },
    VectorMatrixMul {
        result: IRValueDTO,
        vector: IRValueDTO,
        matrix: IRValueDTO,
        shape: [i64; 2],
    },
    VectorGet {
        result: IRValueDTO,
        vector: IRValueDTO,
        index: IRValueDTO,
    },
    MatrixGet {
        result: IRValueDTO,
        matrix: IRValueDTO,
        row: IRValueDTO,
        column: IRValueDTO,
        shape: [i64; 1],
    },
    VectorLength {
        result: IRValueDTO,
        vector: IRValueDTO,
    },
    MatrixRows {
        result: IRValueDTO,
        matrix: IRValueDTO,
        shape: [i64; 1],
    },
    MatrixColumns {
        result: IRValueDTO,
        matrix: IRValueDTO,
        shape: [i64; 1],
    },
    VectorSet {
        vector: IRValueDTO,
        index: IRValueDTO,
        value: IRValueDTO,
    },
    MatrixSet {
        matrix: IRValueDTO,
        row: IRValueDTO,
        column: IRValueDTO,
        value: IRValueDTO,
        shape: [i64; 1],
    },
    ExceptionPack {
        result: IRValueDTO,
        payload: IRValueDTO,
        dynamic_type: NullableDTO<String>,
        source_location: NullableDTO<IRSourceLocationDTO>,
    },
    CatchEntry {
        event: IRValueDTO,
        handler_id: String,
        catch_types: Vec<String>,
    },
    ExceptionMatch {
        result: IRValueDTO,
        event: IRValueDTO,
        catch_type: String,
        catch_all: bool,
    },
    ExceptionPayload {
        result: IRValueDTO,
        event: IRValueDTO,
        catch_type: String,
    },
    ExceptionDestroy {
        event: IRValueDTO,
    },
    Throw {
        event: IRValueDTO,
        target: NullableDTO<String>,
        target_event: NullableDTO<IRValueDTO>,
    },
    Rethrow {
        event: IRValueDTO,
        target: NullableDTO<String>,
        target_event: NullableDTO<IRValueDTO>,
    },
    Propagate {
        event: IRValueDTO,
        target: NullableDTO<String>,
        target_event: NullableDTO<IRValueDTO>,
    },
    Branch {
        condition: IRValueDTO,
        true_target: String,
        false_target: String,
    },
    Jump {
        target: String,
    },
    Return {
        value: NullableDTO<IRValueDTO>,
        transferred_storage: NullableDTO<IRStorageDTO>,
    },
}
