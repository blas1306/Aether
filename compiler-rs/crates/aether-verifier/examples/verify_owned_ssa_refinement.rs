//! Test adapter for differential owned SSA refinement campaigns.

use std::error::Error;
use std::io::{self, Read};

use aether_ir::OwnedSsaModule;
use aether_ir::wire::{IRModuleDTO, SSAModuleV2DTO};
use aether_verifier::verify_owned_ssa_refinement;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
struct Request {
    initial: IRModuleDTO,
    ssa: SSAModuleV2DTO,
}

#[derive(Serialize)]
struct Response {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<aether_verifier::SsaRefinementVerificationError>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut input = Vec::new();
    io::stdin().read_to_end(&mut input)?;
    let request: Request = serde_json::from_slice(&input)?;
    let owned = OwnedSsaModule::from_schema_v2(&request.ssa)?;
    let response = match verify_owned_ssa_refinement(&request.initial, &owned) {
        Ok(()) => Response {
            ok: true,
            error: None,
        },
        Err(error) => Response {
            ok: false,
            error: Some(error),
        },
    };
    serde_json::to_writer(io::stdout().lock(), &response)?;
    Ok(())
}
