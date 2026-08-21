//! Initial IR schema-v1 -> lifecycle-normalized Initial IR schema-v1.

use std::error::Error;
use std::io;

use aether_ir::normalize_lifecycle_v1;
use aether_ir::wire::IRModuleDTO;

fn main() -> Result<(), Box<dyn Error>> {
    let initial: IRModuleDTO = serde_json::from_reader(io::stdin().lock())?;
    let normalized = normalize_lifecycle_v1(&initial, 1)?;
    serde_json::to_writer(io::stdout().lock(), &normalized)?;
    Ok(())
}
