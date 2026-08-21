//! Initial IR schema-v1 -> owned SSA -> authoritative verification -> schema-v2.

use std::error::Error;
use std::io;

use aether_ir::lower_verified_ir_to_ssa_v1;
use aether_ir::wire::IRModuleDTO;
use aether_verifier::verify_owned_ssa;

fn main() -> Result<(), Box<dyn Error>> {
    let initial: IRModuleDTO = serde_json::from_reader(io::stdin().lock())?;
    let owned = lower_verified_ir_to_ssa_v1(&initial, 1, 1)?;
    verify_owned_ssa(&owned)?;
    serde_json::to_writer(io::stdout().lock(), &owned.to_schema_v2())?;
    Ok(())
}
