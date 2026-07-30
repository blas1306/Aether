//! Versioned JSON protocol for the standalone Initial IR verifier.
//!
//! The protocol embeds the canonical [`aether_ir::wire::IRModuleDTO`] document
//! as `module`. The module already carries its IR schema version, so the
//! protocol envelope does not duplicate that field.

use aether_ir::wire::{IR_SCHEMA_VERSION, IRModuleDTO};
use aether_ir::{import_module, parse_strict_json_value};
use aether_verifier::{
    InstructionKind, VerificationErrorCategory, VerificationFailure, VerificationPhase,
    verify_module,
};
use serde::Serialize;
use serde_json::{Map, Value};

/// The only protocol version understood and emitted by this crate.
pub const PROTOCOL_VERSION: u64 = 1;
/// Stable machine-readable identity schema emitted by the executable.
pub const IDENTITY_SCHEMA_VERSION: u64 = 1;
/// Operations implemented by this executable release.
pub const FEATURE_CAPABILITIES: &[&str] = &["verify"];

const VERIFY_OPERATION: &str = "verify";

/// Machine-readable executable identity used by startup compatibility checks.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExecutableIdentity {
    identity_schema_version: u64,
    executable: &'static str,
    version: &'static str,
    protocol_versions: [u64; 1],
    ir_schema_versions: [i64; 1],
    capabilities: &'static [&'static str],
}

/// Return the stable identity for this exact executable release.
#[must_use]
pub const fn executable_identity() -> ExecutableIdentity {
    ExecutableIdentity {
        identity_schema_version: IDENTITY_SCHEMA_VERSION,
        executable: "aether-ir-verifier",
        version: env!("CARGO_PKG_VERSION"),
        protocol_versions: [PROTOCOL_VERSION],
        ir_schema_versions: [IR_SCHEMA_VERSION],
        capabilities: FEATURE_CAPABILITIES,
    }
}

/// Serialize the executable identity as compact deterministic JSON plus newline.
pub fn encode_executable_identity() -> Result<Vec<u8>, serde_json::Error> {
    let mut encoded = serde_json::to_vec(&executable_identity())?;
    encoded.push(b'\n');
    Ok(encoded)
}

/// One deterministic protocol response.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ProtocolResponse {
    protocol_version: u64,
    #[serde(flatten)]
    outcome: ResponseOutcome,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "status")]
enum ResponseOutcome {
    #[serde(rename = "accepted")]
    Accepted,
    #[serde(rename = "rejected")]
    Rejected { diagnostic: VerificationDiagnostic },
    #[serde(rename = "error")]
    Error { error: InfrastructureError },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
struct VerificationDiagnostic {
    phase: &'static str,
    category: &'static str,
    invariant: &'static str,
    message: String,
    context: DiagnosticContext,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
struct DiagnosticContext {
    function_index: Option<usize>,
    function_name: Option<String>,
    block_index: Option<usize>,
    block_name: Option<String>,
    instruction_index: Option<usize>,
    instruction_kind: Option<&'static str>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
struct InfrastructureError {
    kind: &'static str,
    message: String,
}

#[derive(Clone, Copy)]
enum InfrastructureErrorKind {
    EmptyInput,
    MalformedJson,
    RequestSchema,
    UnsupportedProtocolVersion,
    UnsupportedIrSchemaVersion,
    UnsupportedOperation,
    ModuleSchema,
    ModuleImport,
    Normalization,
    InputIo,
    Internal,
}

impl InfrastructureErrorKind {
    const fn wire_name(self) -> &'static str {
        match self {
            Self::EmptyInput => "empty_input",
            Self::MalformedJson => "malformed_json",
            Self::RequestSchema => "request_schema",
            Self::UnsupportedProtocolVersion => "unsupported_protocol_version",
            Self::UnsupportedIrSchemaVersion => "unsupported_ir_schema_version",
            Self::UnsupportedOperation => "unsupported_operation",
            Self::ModuleSchema => "module_schema",
            Self::ModuleImport => "module_import",
            Self::Normalization => "normalization",
            Self::InputIo => "input_io",
            Self::Internal => "internal",
        }
    }
}

impl ProtocolResponse {
    fn accepted() -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            outcome: ResponseOutcome::Accepted,
        }
    }

    fn rejected(diagnostic: VerificationDiagnostic) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            outcome: ResponseOutcome::Rejected { diagnostic },
        }
    }

    fn error(kind: InfrastructureErrorKind, message: impl Into<String>) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            outcome: ResponseOutcome::Error {
                error: InfrastructureError {
                    kind: kind.wire_name(),
                    message: message.into(),
                },
            },
        }
    }

    /// Construct the stable response used when reading stdin fails.
    #[must_use]
    pub fn input_io_error() -> Self {
        Self::error(
            InfrastructureErrorKind::InputIo,
            "failed to read one request from stdin",
        )
    }

    /// Construct the stable response used when an unwind panic reaches the
    /// executable boundary.
    #[must_use]
    pub fn internal_error() -> Self {
        Self::error(
            InfrastructureErrorKind::Internal,
            "the verifier encountered an unexpected internal failure",
        )
    }
}

/// Process exactly one UTF-8 protocol request.
///
/// Every ordinary protocol, schema, import, and semantic outcome is returned
/// as a serializable response value. Panic containment belongs to the binary's
/// outer process boundary rather than this library function.
#[must_use]
pub fn process_request(input: &[u8]) -> ProtocolResponse {
    if input.iter().all(u8::is_ascii_whitespace) {
        return ProtocolResponse::error(InfrastructureErrorKind::EmptyInput, "stdin is empty");
    }

    let Ok(json) = std::str::from_utf8(input) else {
        return malformed_json_response();
    };
    let Ok(value) = parse_strict_json_value(json) else {
        return malformed_json_response();
    };
    process_value(&value)
}

/// Serialize one response as compact deterministic JSON followed by one
/// newline.
pub fn encode_response(response: &ProtocolResponse) -> Result<Vec<u8>, serde_json::Error> {
    let mut encoded = serde_json::to_vec(response)?;
    encoded.push(b'\n');
    Ok(encoded)
}

fn malformed_json_response() -> ProtocolResponse {
    ProtocolResponse::error(
        InfrastructureErrorKind::MalformedJson,
        "stdin must contain exactly one valid UTF-8 JSON value",
    )
}

fn process_value(value: &Value) -> ProtocolResponse {
    let Some(request) = value.as_object() else {
        return request_schema_error("request must be a JSON object");
    };

    let Some(protocol_version) = request.get("protocol_version") else {
        return request_schema_error("request field 'protocol_version' is required");
    };
    let Some(protocol_version) = integer_spelling(protocol_version) else {
        return request_schema_error("request field 'protocol_version' must be an integer");
    };
    if protocol_version != PROTOCOL_VERSION.to_string() {
        return ProtocolResponse::error(
            InfrastructureErrorKind::UnsupportedProtocolVersion,
            format!("unsupported protocol version {protocol_version}; expected {PROTOCOL_VERSION}"),
        );
    }

    let Some(operation) = request.get("operation") else {
        return request_schema_error("request field 'operation' is required");
    };
    let Some(operation) = operation.as_str() else {
        return request_schema_error("request field 'operation' must be a string");
    };
    if operation != VERIFY_OPERATION {
        return ProtocolResponse::error(
            InfrastructureErrorKind::UnsupportedOperation,
            format!("unsupported operation '{operation}'; expected '{VERIFY_OPERATION}'"),
        );
    }

    if request.len() != 3
        || !request.contains_key("protocol_version")
        || !request.contains_key("operation")
        || !request.contains_key("module")
    {
        return request_schema_error(
            "request must contain exactly 'protocol_version', 'operation', and 'module'",
        );
    }

    let Some(module) = request.get("module").and_then(Value::as_object) else {
        return request_schema_error("request field 'module' must be a JSON object");
    };
    if let Some(response) = validate_ir_schema_version(module) {
        return response;
    }

    let Ok(dto) = serde_json::from_value::<IRModuleDTO>(Value::Object(module.clone())) else {
        return ProtocolResponse::error(
            InfrastructureErrorKind::ModuleSchema,
            format!(
                "module does not conform to canonical Initial IR schema version \
                 {IR_SCHEMA_VERSION}"
            ),
        );
    };
    let Ok(module) = import_module(&dto) else {
        return ProtocolResponse::error(
            InfrastructureErrorKind::ModuleImport,
            "canonical Initial IR module cannot be imported by the Rust IR model",
        );
    };

    match verify_module(&module) {
        Ok(()) => ProtocolResponse::accepted(),
        Err(failure) => match diagnostic_from_failure(&failure) {
            Ok(diagnostic) => ProtocolResponse::rejected(diagnostic),
            Err(message) => {
                ProtocolResponse::error(InfrastructureErrorKind::Normalization, message)
            }
        },
    }
}

fn request_schema_error(message: &'static str) -> ProtocolResponse {
    ProtocolResponse::error(InfrastructureErrorKind::RequestSchema, message)
}

fn integer_spelling(value: &Value) -> Option<String> {
    let number = value.as_number()?;
    if number.is_i64() || number.is_u64() {
        Some(number.to_string())
    } else {
        None
    }
}

fn validate_ir_schema_version(module: &Map<String, Value>) -> Option<ProtocolResponse> {
    let schema_version = module.get("schema_version")?;
    let Some(schema_version) = integer_spelling(schema_version) else {
        return Some(ProtocolResponse::error(
            InfrastructureErrorKind::ModuleSchema,
            "module field 'schema_version' must be an integer",
        ));
    };
    if schema_version == IR_SCHEMA_VERSION.to_string() {
        None
    } else {
        Some(ProtocolResponse::error(
            InfrastructureErrorKind::UnsupportedIrSchemaVersion,
            format!(
                "unsupported Initial IR schema version {schema_version}; expected \
                 {IR_SCHEMA_VERSION}"
            ),
        ))
    }
}

fn diagnostic_from_failure(
    failure: &VerificationFailure,
) -> Result<VerificationDiagnostic, &'static str> {
    let invariant = require_invariant(failure.invariant_id())?;
    let phase = phase_wire_name(failure.phase())
        .ok_or("semantic verifier rejection contains an unsupported diagnostic classification")?;
    let category = category_wire_name(failure.category())
        .ok_or("semantic verifier rejection contains an unsupported diagnostic classification")?;
    let context = failure.context();
    Ok(VerificationDiagnostic {
        phase,
        category,
        invariant,
        message: failure.message().to_owned(),
        context: DiagnosticContext {
            function_index: context.function_index,
            function_name: context.function_name.clone(),
            block_index: context.block_index,
            block_name: context.block_name.clone(),
            instruction_index: context.instruction_index,
            instruction_kind: context.instruction_kind.map(instruction_kind_wire_name),
        },
    })
}

fn require_invariant(invariant: Option<&'static str>) -> Result<&'static str, &'static str> {
    invariant.ok_or("semantic verifier rejection is missing a stable invariant ID")
}

const fn phase_wire_name(phase: VerificationPhase) -> Option<&'static str> {
    match phase {
        VerificationPhase::Structure => Some("structure"),
        VerificationPhase::Types => Some("types"),
        VerificationPhase::Ssa => Some("ssa"),
        VerificationPhase::Dominance => Some("dominance"),
        VerificationPhase::Lifecycle => Some("lifecycle"),
        VerificationPhase::Returns => Some("returns"),
        _ => None,
    }
}

const fn category_wire_name(category: VerificationErrorCategory) -> Option<&'static str> {
    match category {
        VerificationErrorCategory::Definitions => Some("definitions"),
        VerificationErrorCategory::Types => Some("types"),
        VerificationErrorCategory::Cfg => Some("cfg"),
        VerificationErrorCategory::Instructions => Some("instructions"),
        VerificationErrorCategory::Returns => Some("returns"),
        VerificationErrorCategory::Lifecycle => Some("lifecycle"),
        VerificationErrorCategory::DataFlow => Some("data_flow"),
        VerificationErrorCategory::Borrowing => Some("borrowing"),
        VerificationErrorCategory::Calls => Some("calls"),
        VerificationErrorCategory::Builtins => Some("builtins"),
        VerificationErrorCategory::Constants => Some("constants"),
        VerificationErrorCategory::Operators => Some("operators"),
        VerificationErrorCategory::Structs => Some("structs"),
        VerificationErrorCategory::MethodResults => Some("method_results"),
        VerificationErrorCategory::Collections => Some("collections"),
        VerificationErrorCategory::LinearAlgebra => Some("linear_algebra"),
        _ => None,
    }
}

#[allow(clippy::too_many_lines)]
const fn instruction_kind_wire_name(kind: InstructionKind) -> &'static str {
    match kind {
        InstructionKind::IRConst => "const",
        InstructionKind::IRLoad => "load",
        InstructionKind::IRStore => "store",
        InstructionKind::IRInitDefault => "init_default",
        InstructionKind::IRCopyInit => "copy_init",
        InstructionKind::IRMoveInit => "move_init",
        InstructionKind::IRAssign => "assign",
        InstructionKind::IRDestroy => "destroy",
        InstructionKind::IRRelocate => "relocate",
        InstructionKind::IRBinaryOp => "binary_op",
        InstructionKind::IRUnaryOp => "unary_op",
        InstructionKind::IRCompareOp => "compare_op",
        InstructionKind::IRCast => "cast",
        InstructionKind::IRCall => "call",
        InstructionKind::IRInvoke => "invoke",
        InstructionKind::IRFunctionRef => "function_ref",
        InstructionKind::IRCallIndirect => "call_indirect",
        InstructionKind::IRInvokeIndirect => "invoke_indirect",
        InstructionKind::IRPrint => "print",
        InstructionKind::IRStructNew => "struct_new",
        InstructionKind::IRClassNew => "class_new",
        InstructionKind::IRClassGet => "class_get",
        InstructionKind::IRClassSet => "class_set",
        InstructionKind::IRInterfaceConstruct => "interface_construct",
        InstructionKind::IRInterfaceCall => "interface_call",
        InstructionKind::IRInvokeInterface => "invoke_interface",
        InstructionKind::IRStructGet => "struct_get",
        InstructionKind::IRStructSet => "struct_set",
        InstructionKind::IRMethodResultNew => "method_result_new",
        InstructionKind::IRMethodResultReceiver => "method_result_receiver",
        InstructionKind::IRMethodResultValue => "method_result_value",
        InstructionKind::IRArrayNew => "array_new",
        InstructionKind::IRListNew => "list_new",
        InstructionKind::IRArrayCopy => "array_copy",
        InstructionKind::IRListCopy => "list_copy",
        InstructionKind::IRListContains => "list_contains",
        InstructionKind::IRListIndexOf => "list_index_of",
        InstructionKind::IRListClear => "list_clear",
        InstructionKind::IRListPush => "list_push",
        InstructionKind::IRListInsert => "list_insert",
        InstructionKind::IRListRemoveAt => "list_remove_at",
        InstructionKind::IRListPop => "list_pop",
        InstructionKind::IRListReverse => "list_reverse",
        InstructionKind::IRSequenceSort => "sequence_sort",
        InstructionKind::IRVectorNew => "vector_new",
        InstructionKind::IRMatrixNew => "matrix_new",
        InstructionKind::IRVectorAdd => "vector_add",
        InstructionKind::IRVectorSub => "vector_sub",
        InstructionKind::IRVectorScale => "vector_scale",
        InstructionKind::IRVectorDot => "vector_dot",
        InstructionKind::IROuterProduct => "outer_product",
        InstructionKind::IRMatrixAdd => "matrix_add",
        InstructionKind::IRMatrixSub => "matrix_sub",
        InstructionKind::IRMatrixScale => "matrix_scale",
        InstructionKind::IRMatrixMatMul => "matrix_mat_mul",
        InstructionKind::IRMatrixVectorMul => "matrix_vector_mul",
        InstructionKind::IRVectorMatrixMul => "vector_matrix_mul",
        InstructionKind::IRArrayGet => "array_get",
        InstructionKind::IRArraySlice => "array_slice",
        InstructionKind::IRListSlice => "list_slice",
        InstructionKind::IRListGet => "list_get",
        InstructionKind::IRVectorGet => "vector_get",
        InstructionKind::IRMatrixGet => "matrix_get",
        InstructionKind::IRVectorLength => "vector_length",
        InstructionKind::IRMatrixRows => "matrix_rows",
        InstructionKind::IRMatrixColumns => "matrix_columns",
        InstructionKind::IRArraySet => "array_set",
        InstructionKind::IRListSet => "list_set",
        InstructionKind::IRVectorSet => "vector_set",
        InstructionKind::IRMatrixSet => "matrix_set",
        InstructionKind::IRArrayLength => "array_length",
        InstructionKind::IRListLength => "list_length",
        InstructionKind::IRListIsEmpty => "list_is_empty",
        InstructionKind::IRPackException => "exception_pack",
        InstructionKind::IRCatchEntry => "catch_entry",
        InstructionKind::IRExceptionMatch => "exception_match",
        InstructionKind::IRExceptionPayload => "exception_payload",
        InstructionKind::IRExceptionDestroy => "exception_destroy",
        InstructionKind::IRThrow => "throw",
        InstructionKind::IRRethrow => "rethrow",
        InstructionKind::IRPropagate => "propagate",
        InstructionKind::IRBranch => "branch",
        InstructionKind::IRJump => "jump",
        InstructionKind::IRReturn => "return",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn response_value(input: &[u8]) -> Value {
        serde_json::to_value(process_request(input)).expect("response must serialize")
    }

    #[test]
    fn accepted_response_has_locked_status_spelling_and_field_shape() {
        let response = ProtocolResponse::accepted();

        assert_eq!(
            encode_response(&response).expect("response must serialize"),
            b"{\"protocol_version\":1,\"status\":\"accepted\"}\n"
        );
    }

    #[test]
    fn rejected_response_serialization_and_null_context_are_locked() {
        let response = ProtocolResponse::rejected(VerificationDiagnostic {
            phase: "types",
            category: "returns",
            invariant: "IRV-026",
            message: "bad return".to_owned(),
            context: DiagnosticContext {
                function_index: None,
                function_name: None,
                block_index: None,
                block_name: None,
                instruction_index: None,
                instruction_kind: None,
            },
        });

        assert_eq!(
            encode_response(&response).expect("response must serialize"),
            b"{\"protocol_version\":1,\"status\":\"rejected\",\"diagnostic\":{\"phase\":\"types\",\
              \"category\":\"returns\",\"invariant\":\"IRV-026\",\"message\":\"bad return\",\
              \"context\":{\"function_index\":null,\"function_name\":null,\"block_index\":null,\
              \"block_name\":null,\"instruction_index\":null,\"instruction_kind\":null}}}\n"
        );
    }

    #[test]
    fn stable_wire_mappings_are_explicit() {
        assert_eq!(
            [
                VerificationPhase::Structure,
                VerificationPhase::Types,
                VerificationPhase::Ssa,
                VerificationPhase::Dominance,
                VerificationPhase::Lifecycle,
                VerificationPhase::Returns,
            ]
            .map(phase_wire_name),
            [
                Some("structure"),
                Some("types"),
                Some("ssa"),
                Some("dominance"),
                Some("lifecycle"),
                Some("returns")
            ]
        );
        assert_eq!(
            [
                VerificationErrorCategory::Definitions,
                VerificationErrorCategory::Types,
                VerificationErrorCategory::Cfg,
                VerificationErrorCategory::Instructions,
                VerificationErrorCategory::Returns,
                VerificationErrorCategory::Lifecycle,
                VerificationErrorCategory::DataFlow,
                VerificationErrorCategory::Borrowing,
                VerificationErrorCategory::Calls,
                VerificationErrorCategory::Builtins,
                VerificationErrorCategory::Constants,
                VerificationErrorCategory::Operators,
                VerificationErrorCategory::Structs,
                VerificationErrorCategory::MethodResults,
                VerificationErrorCategory::Collections,
                VerificationErrorCategory::LinearAlgebra,
            ]
            .map(category_wire_name),
            [
                Some("definitions"),
                Some("types"),
                Some("cfg"),
                Some("instructions"),
                Some("returns"),
                Some("lifecycle"),
                Some("data_flow"),
                Some("borrowing"),
                Some("calls"),
                Some("builtins"),
                Some("constants"),
                Some("operators"),
                Some("structs"),
                Some("method_results"),
                Some("collections"),
                Some("linear_algebra"),
            ]
        );
        assert_eq!(
            [
                InfrastructureErrorKind::EmptyInput,
                InfrastructureErrorKind::MalformedJson,
                InfrastructureErrorKind::RequestSchema,
                InfrastructureErrorKind::UnsupportedProtocolVersion,
                InfrastructureErrorKind::UnsupportedIrSchemaVersion,
                InfrastructureErrorKind::UnsupportedOperation,
                InfrastructureErrorKind::ModuleSchema,
                InfrastructureErrorKind::ModuleImport,
                InfrastructureErrorKind::Normalization,
                InfrastructureErrorKind::InputIo,
                InfrastructureErrorKind::Internal,
            ]
            .map(InfrastructureErrorKind::wire_name),
            [
                "empty_input",
                "malformed_json",
                "request_schema",
                "unsupported_protocol_version",
                "unsupported_ir_schema_version",
                "unsupported_operation",
                "module_schema",
                "module_import",
                "normalization",
                "input_io",
                "internal",
            ]
        );
    }

    #[test]
    fn every_instruction_kind_spelling_is_locked() {
        let cases = [
            (InstructionKind::IRConst, "const"),
            (InstructionKind::IRLoad, "load"),
            (InstructionKind::IRStore, "store"),
            (InstructionKind::IRInitDefault, "init_default"),
            (InstructionKind::IRCopyInit, "copy_init"),
            (InstructionKind::IRMoveInit, "move_init"),
            (InstructionKind::IRAssign, "assign"),
            (InstructionKind::IRDestroy, "destroy"),
            (InstructionKind::IRRelocate, "relocate"),
            (InstructionKind::IRBinaryOp, "binary_op"),
            (InstructionKind::IRUnaryOp, "unary_op"),
            (InstructionKind::IRCompareOp, "compare_op"),
            (InstructionKind::IRCast, "cast"),
            (InstructionKind::IRCall, "call"),
            (InstructionKind::IRFunctionRef, "function_ref"),
            (InstructionKind::IRCallIndirect, "call_indirect"),
            (InstructionKind::IRPrint, "print"),
            (InstructionKind::IRStructNew, "struct_new"),
            (InstructionKind::IRClassNew, "class_new"),
            (InstructionKind::IRClassGet, "class_get"),
            (InstructionKind::IRClassSet, "class_set"),
            (InstructionKind::IRInterfaceConstruct, "interface_construct"),
            (InstructionKind::IRInterfaceCall, "interface_call"),
            (InstructionKind::IRStructGet, "struct_get"),
            (InstructionKind::IRStructSet, "struct_set"),
            (InstructionKind::IRMethodResultNew, "method_result_new"),
            (
                InstructionKind::IRMethodResultReceiver,
                "method_result_receiver",
            ),
            (InstructionKind::IRMethodResultValue, "method_result_value"),
            (InstructionKind::IRArrayNew, "array_new"),
            (InstructionKind::IRListNew, "list_new"),
            (InstructionKind::IRArrayCopy, "array_copy"),
            (InstructionKind::IRListCopy, "list_copy"),
            (InstructionKind::IRListContains, "list_contains"),
            (InstructionKind::IRListIndexOf, "list_index_of"),
            (InstructionKind::IRListClear, "list_clear"),
            (InstructionKind::IRListPush, "list_push"),
            (InstructionKind::IRListInsert, "list_insert"),
            (InstructionKind::IRListRemoveAt, "list_remove_at"),
            (InstructionKind::IRListPop, "list_pop"),
            (InstructionKind::IRListReverse, "list_reverse"),
            (InstructionKind::IRSequenceSort, "sequence_sort"),
            (InstructionKind::IRVectorNew, "vector_new"),
            (InstructionKind::IRMatrixNew, "matrix_new"),
            (InstructionKind::IRVectorAdd, "vector_add"),
            (InstructionKind::IRVectorSub, "vector_sub"),
            (InstructionKind::IRVectorScale, "vector_scale"),
            (InstructionKind::IRVectorDot, "vector_dot"),
            (InstructionKind::IROuterProduct, "outer_product"),
            (InstructionKind::IRMatrixAdd, "matrix_add"),
            (InstructionKind::IRMatrixSub, "matrix_sub"),
            (InstructionKind::IRMatrixScale, "matrix_scale"),
            (InstructionKind::IRMatrixMatMul, "matrix_mat_mul"),
            (InstructionKind::IRMatrixVectorMul, "matrix_vector_mul"),
            (InstructionKind::IRVectorMatrixMul, "vector_matrix_mul"),
            (InstructionKind::IRArrayGet, "array_get"),
            (InstructionKind::IRArraySlice, "array_slice"),
            (InstructionKind::IRListSlice, "list_slice"),
            (InstructionKind::IRListGet, "list_get"),
            (InstructionKind::IRVectorGet, "vector_get"),
            (InstructionKind::IRMatrixGet, "matrix_get"),
            (InstructionKind::IRVectorLength, "vector_length"),
            (InstructionKind::IRMatrixRows, "matrix_rows"),
            (InstructionKind::IRMatrixColumns, "matrix_columns"),
            (InstructionKind::IRArraySet, "array_set"),
            (InstructionKind::IRListSet, "list_set"),
            (InstructionKind::IRVectorSet, "vector_set"),
            (InstructionKind::IRMatrixSet, "matrix_set"),
            (InstructionKind::IRArrayLength, "array_length"),
            (InstructionKind::IRListLength, "list_length"),
            (InstructionKind::IRListIsEmpty, "list_is_empty"),
            (InstructionKind::IRBranch, "branch"),
            (InstructionKind::IRJump, "jump"),
            (InstructionKind::IRReturn, "return"),
        ];

        assert_eq!(cases.len(), 73);
        for (kind, spelling) in cases {
            assert_eq!(instruction_kind_wire_name(kind), spelling);
        }
    }

    #[test]
    fn missing_invariant_is_an_infrastructure_error() {
        let message = require_invariant(None).expect_err("missing invariant must not reject");
        let response = ProtocolResponse::error(InfrastructureErrorKind::Normalization, message);
        let value = serde_json::to_value(response).expect("response must serialize");

        assert_eq!(value["status"], "error");
        assert_eq!(value["error"]["kind"], "normalization");
    }

    #[test]
    fn rejects_duplicate_keys_and_trailing_json() {
        for input in [
            br#"{"protocol_version":1,"protocol_version":1,"operation":"verify","module":{}}"#
                .as_slice(),
            br#"{"protocol_version":1,"operation":"verify","module":{}} null"#.as_slice(),
        ] {
            assert_eq!(response_value(input)["error"]["kind"], "malformed_json");
        }
    }

    #[test]
    fn optional_context_is_encoded_as_explicit_nulls() {
        let input = br#"{"protocol_version":1,"operation":"verify","module":{"schema_version":1,"functions":[{"name":"main","parameters":[],"return_type":{"tag":"void"},"blocks":[{"name":"entry","instructions":[]}]}],"structs":[]}}"#;
        let value = response_value(input);

        assert_eq!(value["status"], "rejected");
        assert_eq!(value["diagnostic"]["invariant"], "IRV-018");
        assert_eq!(value["diagnostic"]["context"]["function_index"], 0);
        assert_eq!(value["diagnostic"]["context"]["block_index"], 0);
        assert!(value["diagnostic"]["context"]["instruction_index"].is_null());
        assert!(value["diagnostic"]["context"]["instruction_kind"].is_null());
    }

    #[test]
    fn version_and_operation_rejections_are_distinct() {
        let protocol = response_value(
            br#"{"protocol_version":2,"operation":"verify","module":{"schema_version":1,"functions":[],"structs":[]}}"#,
        );
        let schema = response_value(
            br#"{"protocol_version":1,"operation":"verify","module":{"schema_version":2,"functions":[],"structs":[]}}"#,
        );
        let operation = response_value(
            br#"{"protocol_version":1,"operation":"lint","module":{"schema_version":1,"functions":[],"structs":[]}}"#,
        );

        assert_eq!(protocol["error"]["kind"], "unsupported_protocol_version");
        assert_eq!(schema["error"]["kind"], "unsupported_ir_schema_version");
        assert_eq!(operation["error"]["kind"], "unsupported_operation");
    }

    #[test]
    fn missing_operation_is_a_request_schema_error() {
        let response = response_value(
            br#"{"protocol_version":1,"module":{"schema_version":1,"functions":[],"structs":[]}}"#,
        );

        assert_eq!(response["status"], "error");
        assert_eq!(response["error"]["kind"], "request_schema");
    }
}
