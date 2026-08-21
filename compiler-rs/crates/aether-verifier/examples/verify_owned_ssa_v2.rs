//! Schema-v2 -> owned SSA -> authoritative verification -> schema-v2.

use std::error::Error;
use std::io;

use aether_ir::OwnedSsaModule;
use aether_ir::wire::SSAModuleV2DTO;
use aether_verifier::verify_owned_ssa;

fn main() -> Result<(), Box<dyn Error>> {
    let wire: SSAModuleV2DTO = serde_json::from_reader(io::stdin().lock())?;
    let owned = OwnedSsaModule::from_schema_v2(&wire)?;
    verify_owned_ssa(&owned)?;
    serde_json::to_writer(io::stdout().lock(), &owned.to_schema_v2())?;
    Ok(())
}
