//! Persistent Initial IR to verified OwnedSsa shadow companion.

use std::error::Error;
use std::io::{self, Read, Write};
use std::time::Instant;

use aether_ir::wire::IRModuleDTO;
use aether_ir::{
    lower_normalized_ir_to_ssa_v1, lower_verified_ir_to_ssa_v1, normalize_lifecycle_v1,
};
use aether_verifier::verify_owned_ssa;
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

fn write_frame(out: &mut impl Write, value: &impl Serialize) -> Result<(), Box<dyn Error>> {
    let bytes = serde_json::to_vec(value)?;
    out.write_all(&(bytes.len() as u32).to_be_bytes())?;
    out.write_all(&bytes)?;
    out.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if arguments.first().map(String::as_str) != Some("--persistent") {
        return Err("aether-ssa-shadow requires --persistent".into());
    }
    let characterize_performance = match arguments.get(1).map(String::as_str) {
        None => false,
        Some("--characterize-performance") if arguments.len() == 2 => true,
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
        let response = (|| -> Result<SuccessResponse, Box<dyn Error>> {
            if !characterize_performance {
                let initial: IRModuleDTO = serde_json::from_slice(&body)?;
                let owned = lower_verified_ir_to_ssa_v1(&initial, 1, 1)?;
                verify_owned_ssa(&owned)?;
                return Ok(SuccessResponse {
                    ok: true,
                    ssa: owned.to_schema_v2(),
                    performance: None,
                });
            }

            let request_started = Instant::now();

            let started = Instant::now();
            let initial: IRModuleDTO = serde_json::from_slice(&body)?;
            let input_parsing_ns = started.elapsed().as_nanos() as u64;

            let started = Instant::now();
            let normalized = normalize_lifecycle_v1(&initial, 1)?;
            let lifecycle_normalization_ns = started.elapsed().as_nanos() as u64;

            let started = Instant::now();
            let owned = lower_normalized_ir_to_ssa_v1(&normalized)?;
            let ssa_lowering_ns = started.elapsed().as_nanos() as u64;

            let started = Instant::now();
            verify_owned_ssa(&owned)?;
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
                    request_compute_total: total_ns,
                }),
            })
        })()
        .map(Response::Success)
        .unwrap_or_else(|error| {
            Response::Failure(FailureResponse {
                ok: false,
                error: error.to_string(),
            })
        });
        write_frame(&mut output, &response)?;
    }
}
