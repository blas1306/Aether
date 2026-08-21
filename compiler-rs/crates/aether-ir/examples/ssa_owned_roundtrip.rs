//! Schema-v2 -> owned SSA -> schema-v2 qualification adapter.

use std::io::{self, Read};

use aether_ir::OwnedSsaModule;
use aether_ir::wire::SSAWireModuleDTO;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let dto = match serde_json::from_str::<SSAWireModuleDTO>(&input)? {
        SSAWireModuleDTO::V2(dto) => dto,
        SSAWireModuleDTO::V1(_) => return Err("owned SSA import requires schema-v2".into()),
    };
    let owned = OwnedSsaModule::from_schema_v2(&dto)?;
    serde_json::to_writer(io::stdout().lock(), &owned.to_schema_v2())?;
    Ok(())
}
