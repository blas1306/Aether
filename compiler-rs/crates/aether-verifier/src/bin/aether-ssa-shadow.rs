//! Persistent Initial IR to verified OwnedSsa shadow companion.

use std::error::Error;
use std::io::{self, Read, Write};

use aether_ir::lower_verified_ir_to_ssa_v1;
use aether_ir::wire::IRModuleDTO;
use aether_verifier::verify_owned_ssa;
use serde_json::{Value, json};

fn write_frame(out: &mut impl Write, value: &Value) -> Result<(), Box<dyn Error>> {
    let bytes = serde_json::to_vec(value)?;
    out.write_all(&(bytes.len() as u32).to_be_bytes())?;
    out.write_all(&bytes)?;
    out.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    if std::env::args().nth(1).as_deref() != Some("--persistent") {
        return Err("aether-ssa-shadow requires --persistent".into());
    }
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    write_frame(
        &mut output,
        &json!({"product":"aether-ssa-shadow","protocol_version":1}),
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
        let response = (|| -> Result<Value, Box<dyn Error>> {
            let initial: IRModuleDTO = serde_json::from_slice(&body)?;
            let owned = lower_verified_ir_to_ssa_v1(&initial, 1, 1)?;
            verify_owned_ssa(&owned)?;
            Ok(json!({"ok":true,"ssa":owned.to_schema_v2()}))
        })()
        .unwrap_or_else(|error| json!({"ok":false,"error":error.to_string()}));
        write_frame(&mut output, &response)?;
    }
}
