//! Standalone stdin/stdout entry point for the versioned verifier protocol.

use std::env;
use std::io::{self, Read as _, Write as _};
use std::panic::{self, AssertUnwindSafe};
use std::process::ExitCode;

use aether_ir::wire::IR_SCHEMA_VERSION;
use aether_ir_verifier::{
    FEATURE_CAPABILITIES, PROTOCOL_VERSION, ProtocolResponse, encode_executable_identity,
    encode_response, process_request,
};

fn main() -> ExitCode {
    let arguments: Vec<_> = env::args_os().skip(1).collect();
    if arguments.len() == 1 && arguments[0] == "--persistent" {
        return run_persistent();
    }
    if !arguments.is_empty() {
        return run_metadata_command(&arguments);
    }

    let mut input = Vec::new();
    let response = if io::stdin().read_to_end(&mut input).is_err() {
        ProtocolResponse::input_io_error()
    } else {
        catch_request_panic(&input)
    };

    let Ok(encoded) = encode_response(&response) else {
        return ExitCode::FAILURE;
    };
    let mut stdout = io::stdout().lock();
    if stdout
        .write_all(&encoded)
        .and_then(|()| stdout.flush())
        .is_err()
    {
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;

/// Persistent transport v1: unsigned 32-bit big-endian length followed by the
/// unchanged protocol-v1 JSON payload.  The first frame is executable identity.
fn run_persistent() -> ExitCode {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut output = stdout.lock();
    let Ok(identity) = encode_executable_identity() else {
        return ExitCode::FAILURE;
    };
    if write_frame(&mut output, &identity).is_err() {
        return ExitCode::FAILURE;
    }
    loop {
        let mut header = [0_u8; 4];
        match input.read(&mut header[..1]) {
            Ok(0) => return ExitCode::SUCCESS,
            Ok(1) => {}
            Ok(_) => unreachable!(),
            Err(_) => return ExitCode::FAILURE,
        }
        if input.read_exact(&mut header[1..]).is_err() {
            return ExitCode::FAILURE;
        }
        let length = u32::from_be_bytes(header) as usize;
        if length > MAX_FRAME_BYTES {
            let _ = io::stderr()
                .write_all(b"aether-ir-verifier: request frame exceeds transport limit\n");
            return ExitCode::FAILURE;
        }
        let mut request = vec![0_u8; length];
        if input.read_exact(&mut request).is_err() {
            return ExitCode::FAILURE;
        }
        let response = catch_request_panic(&request);
        let Ok(encoded) = encode_response(&response) else {
            return ExitCode::FAILURE;
        };
        if write_frame(&mut output, &encoded).is_err() {
            return ExitCode::FAILURE;
        }
    }
}

fn write_frame(output: &mut impl io::Write, payload: &[u8]) -> io::Result<()> {
    let length = u32::try_from(payload.len())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "frame is too large"))?;
    output.write_all(&length.to_be_bytes())?;
    output.write_all(payload)?;
    output.flush()
}

fn run_metadata_command(arguments: &[std::ffi::OsString]) -> ExitCode {
    let encoded = if arguments.len() == 1
        && (arguments[0] == "--identity" || arguments[0] == "--metadata")
    {
        encode_executable_identity()
    } else if arguments.len() == 1 && arguments[0] == "--version" {
        Ok(format!(
            "aether-ir-verifier {} (protocol {PROTOCOL_VERSION}, IR schema {}; capabilities: {})\n",
            env!("CARGO_PKG_VERSION"),
            IR_SCHEMA_VERSION,
            FEATURE_CAPABILITIES.join(",")
        )
        .into_bytes())
    } else {
        let _ = io::stderr().write_all(
            b"aether-ir-verifier: expected no arguments, --identity, --metadata, --persistent, or --version\n",
        );
        return ExitCode::from(2);
    };
    let Ok(encoded) = encoded else {
        return ExitCode::FAILURE;
    };
    if io::stdout()
        .write_all(&encoded)
        .and_then(|()| io::stdout().flush())
        .is_err()
    {
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

fn catch_request_panic(input: &[u8]) -> ProtocolResponse {
    catch_panic(|| process_request(input))
}

fn catch_panic(operation: impl FnOnce() -> ProtocolResponse) -> ProtocolResponse {
    let previous_hook = panic::take_hook();
    panic::set_hook(Box::new(|_| {}));
    let outcome = panic::catch_unwind(AssertUnwindSafe(operation));
    panic::set_hook(previous_hook);
    outcome.unwrap_or_else(|_| ProtocolResponse::internal_error())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn panic_payload_is_replaced_with_stable_internal_response() {
        let response = catch_panic(|| panic!("sensitive panic payload"));

        assert_eq!(
            encode_response(&response).expect("internal response must serialize"),
            b"{\"protocol_version\":1,\"status\":\"error\",\"error\":{\"kind\":\"internal\",\
              \"message\":\"the verifier encountered an unexpected internal failure\"}}\n"
        );
    }
}
