//! Standalone stdin/stdout entry point for the versioned verifier protocol.

use std::io::{self, Read as _, Write as _};
use std::panic::{self, AssertUnwindSafe};
use std::process::ExitCode;

use aether_ir_verifier::{ProtocolResponse, encode_response, process_request};

fn main() -> ExitCode {
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
