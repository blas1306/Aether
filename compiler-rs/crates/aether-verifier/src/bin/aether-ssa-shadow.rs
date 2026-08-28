//! Persistent Initial IR to verified OwnedSsa shadow companion.

use std::error::Error;
use std::io::{self, Read, Write};
use std::time::Instant;

use aether_ir::wire::IRModuleDTO;
use aether_ir::{characterize_lower_normalized_ir_to_ssa_v1, normalize_lifecycle_v1};
use aether_verifier::{
    COMPILER_CORE_API_VERSION, COMPILER_CORE_INPUT_SCHEMA_VERSIONS,
    COMPILER_CORE_OUTPUT_SCHEMA_VERSIONS, COMPILER_CORE_PROTOCOL_VERSION, CompilerCore,
    CompilerError, verify_owned_ssa,
};
use serde::Serialize;
use serde_json::json;

#[derive(Serialize)]
struct SuccessResponse {
    ok: bool,
    ssa: aether_ir::wire::SSAModuleV2DTO,
    #[serde(skip_serializing_if = "Option::is_none")]
    performance: Option<PerformanceResponse>,
}

#[derive(Serialize)]
struct FailureResponse {
    ok: bool,
    error: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    diagnostic: Option<serde_json::Value>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Response {
    Success(SuccessResponse),
    Failure(FailureResponse),
}

#[derive(Serialize)]
struct PerformanceResponse {
    clock: &'static str,
    unit: &'static str,
    phases: PerformancePhases,
    ssa_lowering_phases: SsaLoweringPerformancePhases,
    request_compute_total: u64,
}

#[derive(Serialize)]
struct PerformancePhases {
    rust_input_parsing: u64,
    rust_lifecycle_normalization: u64,
    rust_ssa_lowering: u64,
    rust_owned_ssa_verification: u64,
    rust_schema_v2_materialization: u64,
    rust_orchestration_unattributed: u64,
}

#[derive(Serialize)]
struct SsaLoweringPerformancePhases {
    cfg_construction: u64,
    reachability_and_rpo: u64,
    chk_idom: u64,
    dominator_tree: u64,
    dominance_frontier: u64,
    liveness: u64,
    definite_initialization: u64,
    phi_placement: u64,
    renaming: u64,
    remaining_lowering: u64,
}

fn write_frame(out: &mut impl Write, value: &impl Serialize) -> Result<(), Box<dyn Error>> {
    let bytes = serde_json::to_vec(value)?;
    out.write_all(&(bytes.len() as u32).to_be_bytes())?;
    out.write_all(&bytes)?;
    out.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if arguments.as_slice() == ["--distribution-metadata"] {
        println!(
            "{}",
            serde_json::to_string(&json!({
                "build_identity": option_env!("AETHER_COMPILER_CORE_BUILD_IDENTITY")
                    .unwrap_or("unversioned-development-build"),
                "compiler_core_api_version": COMPILER_CORE_API_VERSION,
                "input_schema_versions": COMPILER_CORE_INPUT_SCHEMA_VERSIONS,
                "output_schema_versions": COMPILER_CORE_OUTPUT_SCHEMA_VERSIONS,
                "product": "aether-ssa-shadow",
                "product_version": env!("CARGO_PKG_VERSION"),
                "protocol_version": COMPILER_CORE_PROTOCOL_VERSION,
            }))?
        );
        return Ok(());
    }
    if arguments.first().map(String::as_str) != Some("--persistent") {
        return Err("aether-ssa-shadow requires --persistent".into());
    }
    let (characterize_performance, qualification_structured_errors) =
        match arguments.get(1).map(String::as_str) {
            None => (false, false),
            Some("--characterize-performance") if arguments.len() == 2 => (true, false),
            Some("--qualification-structured-errors") if arguments.len() == 2 => (false, true),
            _ => return Err("unsupported aether-ssa-shadow argument".into()),
        };
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    write_frame(
        &mut output,
        &json!({
            "product":"aether-ssa-shadow",
            "product_version":env!("CARGO_PKG_VERSION"),
            "protocol_version":1,
            "input_schema_version":1,
            "output_schema_version":2
        }),
    )?;
    loop {
        let mut header = [0_u8; 4];
        match input.read_exact(&mut header) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => return Ok(()),
            Err(error) => return Err(error.into()),
        }
        let length = u32::from_be_bytes(header) as usize;
        if length > 64 * 1024 * 1024 {
            return Err("request exceeds limit".into());
        }
        let mut body = vec![0; length];
        input.read_exact(&mut body)?;
        let response = (|| -> Result<SuccessResponse, RequestFailure> {
            if !characterize_performance {
                let initial: IRModuleDTO =
                    serde_json::from_slice(&body).map_err(RequestFailure::Input)?;
                let owned = CompilerCore
                    .lower_verified_ssa(initial)
                    .map_err(RequestFailure::Core)?;
                return Ok(SuccessResponse {
                    ok: true,
                    ssa: owned.to_schema_v2(),
                    performance: None,
                });
            }

            let request_started = Instant::now();

            let started = Instant::now();
            let initial: IRModuleDTO =
                serde_json::from_slice(&body).map_err(RequestFailure::Input)?;
            let input_parsing_ns = started.elapsed().as_nanos() as u64;

            let started = Instant::now();
            let normalized = normalize_lifecycle_v1(&initial, 1)
                .map_err(|error| RequestFailure::Instrumented(error.to_string()))?;
            let lifecycle_normalization_ns = started.elapsed().as_nanos() as u64;

            let started = Instant::now();
            let (owned, mut lowering_phases) =
                characterize_lower_normalized_ir_to_ssa_v1(&normalized)
                    .map_err(|error| RequestFailure::Instrumented(error.to_string()))?;
            let ssa_lowering_ns = started.elapsed().as_nanos() as u64;
            lowering_phases.remaining_lowering_ns +=
                ssa_lowering_ns.saturating_sub(lowering_phases.measured_ns());

            let started = Instant::now();
            verify_owned_ssa(&owned)
                .map_err(|error| RequestFailure::Instrumented(error.to_string()))?;
            let owned_ssa_verification_ns = started.elapsed().as_nanos() as u64;

            let started = Instant::now();
            let ssa = owned.to_schema_v2();
            let schema_v2_materialization_ns = started.elapsed().as_nanos() as u64;

            let measured_ns = input_parsing_ns
                + lifecycle_normalization_ns
                + ssa_lowering_ns
                + owned_ssa_verification_ns
                + schema_v2_materialization_ns;
            let total_ns = request_started.elapsed().as_nanos() as u64;
            Ok(SuccessResponse {
                ok: true,
                ssa,
                performance: Some(PerformanceResponse {
                    clock: "std::time::Instant",
                    unit: "nanoseconds",
                    phases: PerformancePhases {
                        rust_input_parsing: input_parsing_ns,
                        rust_lifecycle_normalization: lifecycle_normalization_ns,
                        rust_ssa_lowering: ssa_lowering_ns,
                        rust_owned_ssa_verification: owned_ssa_verification_ns,
                        rust_schema_v2_materialization: schema_v2_materialization_ns,
                        rust_orchestration_unattributed: total_ns.saturating_sub(measured_ns),
                    },
                    ssa_lowering_phases: SsaLoweringPerformancePhases {
                        cfg_construction: lowering_phases.cfg_construction_ns,
                        reachability_and_rpo: lowering_phases.reachability_and_rpo_ns,
                        chk_idom: lowering_phases.chk_idom_ns,
                        dominator_tree: lowering_phases.dominator_tree_ns,
                        dominance_frontier: lowering_phases.dominance_frontier_ns,
                        liveness: lowering_phases.liveness_ns,
                        definite_initialization: lowering_phases.definite_initialization_ns,
                        phi_placement: lowering_phases.phi_placement_ns,
                        renaming: lowering_phases.renaming_ns,
                        remaining_lowering: lowering_phases.remaining_lowering_ns,
                    },
                    request_compute_total: total_ns,
                }),
            })
        })()
        .map(Response::Success)
        .unwrap_or_else(|error| {
            Response::Failure(FailureResponse {
                ok: false,
                error: error.to_string(),
                diagnostic: qualification_structured_errors.then(|| error.diagnostic()),
            })
        });
        write_frame(&mut output, &response)?;
    }
}

enum RequestFailure {
    Input(serde_json::Error),
    Core(CompilerError),
    Instrumented(String),
}

impl RequestFailure {
    fn diagnostic(&self) -> serde_json::Value {
        match self {
            Self::Input(_) => json!({
                "kind": "binding",
                "category": "input_schema",
                "phase": "initial_ir_import",
                "code": "CORE-BIND-INPUT-001",
                "function": null,
                "block": null,
                "source_location": null,
            }),
            Self::Core(error) => {
                let mut value =
                    serde_json::to_value(error).expect("CompilerError serialization is infallible");
                value
                    .as_object_mut()
                    .expect("CompilerError serializes as an object")
                    .remove("message");
                value
            }
            Self::Instrumented(_) => json!({
                "kind": "internal",
                "category": "instrumented_companion",
                "phase": "performance_characterization",
                "code": "CORE-COMPANION-INSTRUMENTED-001",
                "function": null,
                "block": null,
                "source_location": null,
            }),
        }
    }
}

impl std::fmt::Display for RequestFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Input(error) => error.fmt(formatter),
            Self::Core(error) => error.fmt(formatter),
            Self::Instrumented(message) => formatter.write_str(message),
        }
    }
}
